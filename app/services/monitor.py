from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import load_config
from app.repositories import (
    get_monitor,
    get_page_profile,
    get_post,
    has_replied,
    list_monitors,
    mark_replied,
    unmark_replied,
    update_monitor,
    upsert_comment,
    get_auto_monitor_config,
    list_auto_monitor_schedules,
    mark_auto_monitor_triggered,
    list_accounts,
    create_monitor,
    list_monitored_post_ids,
)
from app.services.ai_reply import AIReplyService
from app.services.facebook import FacebookService

logger = logging.getLogger("uvicorn.error")

# How often the scheduler loop wakes up to check for due monitors (seconds).
_TICK_INTERVAL = 1
# Limit maximum concurrent monitor tasks to avoid network congestion and API rate limits.
_MAX_CONCURRENT_MONITORS = 5


class MonitorService:
    def __init__(self):
        self._task: asyncio.Task[None] | None = None
        self._running_monitors: set[int] = set()
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_MONITORS)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run_loop(), name="monitor-loop")
        logger.info("[monitor] background scheduler started (tick=%ss, max_concurrent=%s)", _TICK_INTERVAL, _MAX_CONCURRENT_MONITORS)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[monitor] background scheduler stopped")

    async def run_monitor_now(self, monitor_id: int) -> dict[str, Any]:
        """Trigger a single monitor immediately (used by API)."""
        monitor = get_monitor(monitor_id)
        if monitor is None:
            raise ValueError(f"Monitor {monitor_id} not found")
        return await self._execute_monitor(monitor)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("[monitor] unexpected error in tick: %s", exc)
            await asyncio.sleep(_TICK_INTERVAL)

    async def _tick(self) -> None:
        await self._check_auto_monitor_schedules()
        
        monitors = list_monitors()
        now = datetime.now(timezone.utc)
        for monitor in monitors:
            if not monitor["enabled"]:
                continue
            monitor_id = monitor["id"]
            if monitor_id in self._running_monitors:
                continue  # skip if already running

            last_run = monitor.get("last_run_at")
            if last_run:
                try:
                    last_run_dt = datetime.fromisoformat(last_run)
                    if last_run_dt.tzinfo is None:
                        last_run_dt = last_run_dt.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_run_dt).total_seconds()
                    if elapsed < monitor["interval_seconds"]:
                        continue
                except ValueError:
                    pass  # bad timestamp, run anyway

            asyncio.create_task(
                self._safe_execute(monitor),
                name=f"monitor-{monitor_id}",
            )

    async def _check_auto_monitor_schedules(self) -> None:
        config = get_auto_monitor_config()
        if not config.get("enabled"):
            return

        # Use system local time for comparison with user-entered "HH:MM"
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")
        current_minute_key = now.strftime("%Y-%m-%d %H:%M")

        schedules = list_auto_monitor_schedules()
        for schedule in schedules:
            if not schedule.get("enabled"):
                continue
            if schedule["trigger_time"] == current_time_str:
                if schedule.get("last_triggered_at") != current_minute_key:
                    logger.info("[monitor] auto-monitor schedule triggered for %s", current_time_str)
                    # Use a task to not block the main loop
                    asyncio.create_task(self._run_auto_discovery(config["max_posts"]))
                    mark_auto_monitor_triggered(schedule["id"], current_minute_key)

    async def _run_auto_discovery(self, max_posts: int) -> None:
        logger.info("[monitor] starting auto post discovery (max_posts=%s)", max_posts)
        accounts = list_accounts()
        for account in accounts:
            # We check for page_access_token to ensure account is somewhat valid
            if not account.get("page_access_token"):
                continue
            
            try:
                page_id = account["page_id"]
                from app.services.sync import SyncService
                from app.config import load_config
                
                cfg = load_config(account_id=account["id"])
                sync_svc = SyncService(cfg)
                
                # Fetch recent posts (limit 15 for discovery)
                logger.info("[monitor] auto-discovery: fetching posts for account %s (%s)", account["name"], page_id)
                async for step in sync_svc.sync_all_gen(post_limit=15):
                    pass
                
                # After sync, get all post IDs for this page and their monitor status
                from app.repositories import list_posts
                posts = list_posts(page_id=page_id, limit=30)
                monitored_ids = list_monitored_post_ids(page_id)
                
                current_monitor_count = len(monitored_ids)
                if current_monitor_count >= max_posts:
                    logger.info("[monitor] account %s already has %s monitors (limit %s), skipping discovery", 
                                account["name"], current_monitor_count, max_posts)
                    continue
                
                newly_added = 0
                for post in posts:
                    if post["id"] not in monitored_ids:
                        create_monitor(post["id"], interval_seconds=300)
                        monitored_ids.add(post["id"])
                        newly_added += 1
                        current_monitor_count += 1
                        if current_monitor_count >= max_posts:
                            break
                
                if newly_added > 0:
                    logger.info("[monitor] account %s: automatically added %s new monitors", account["name"], newly_added)
                
            except Exception as exc:
                logger.error("[monitor] auto-discovery failed for account %s: %s", account.get("name"), exc)

    async def _safe_execute(self, monitor: dict[str, Any]) -> None:
        monitor_id = monitor["id"]
        self._running_monitors.add(monitor_id)
        try:
            async with self._semaphore:
                await self._execute_monitor(monitor)
        except Exception as exc:
            logger.exception("[monitor] monitor=%s failed with exception", monitor_id)
            update_monitor(
                monitor_id,
                last_run_at=datetime.now(timezone.utc).isoformat(),
                last_run_status=f"ERROR: {type(exc).__name__}: {str(exc)[:300]}",
            )
        finally:
            self._running_monitors.discard(monitor_id)

    async def _execute_monitor(self, monitor: dict[str, Any]) -> dict[str, Any]:
        monitor_id = monitor["id"]
        post_id = monitor["post_id"]

        logger.info("[monitor] running monitor=%s post=%s (unlimited depth mode)", monitor_id, post_id)

        post = get_post(post_id) or {}
        # 优先从数据库中获取规范化的数字 Page ID
        page_id = str(post.get("page_id", ""))
        if not page_id:
            raise RuntimeError(f"monitor={monitor_id} 关联帖子缺失 page_id")

        config = load_config(page_id=page_id)
        facebook = FacebookService(config)
        ai = AIReplyService(config)

        # 获取最新的评论（包含回复）
        comments = await facebook.fetch_comments_for_post(post_id, limit=200)

        # 1. 识别并清理本地已删除的评论
        remote_comment_ids = set()
        def _collect_ids(cs: list[dict[str, Any]]):
            for c in cs:
                remote_comment_ids.add(c["id"])
                if "replies" in c and "data" in c["replies"]:
                    _collect_ids(c["replies"]["data"])
        
        _collect_ids(comments)

        from app.repositories import list_comments_by_post_ids, delete_comment_local
        local_comments_map = list_comments_by_post_ids([post_id])
        local_comments = local_comments_map.get(post_id, [])
        
        # 展平本地所有评论 ID (包括嵌套的)
        def _get_local_ids(cs: list[dict[str, Any]], target_set: set[str]):
            for c in cs:
                target_set.add(c["id"])
                if "replies" in c and c["replies"]:
                    _get_local_ids(c["replies"], target_set)
        
        local_comment_ids = set()
        _get_local_ids(local_comments, local_comment_ids)

        for lid in local_comment_ids:
            if lid not in remote_comment_ids:
                logger.info("[monitor] 发现已删除评论，清理本地记录: %s", lid)
                delete_comment_local(lid)

        # 2. 更新/插入最新评论到本地数据库
        for comment in comments:
            upsert_comment(post_id, None, comment)

        # 获取主页资料，用于获取主页名称和确认数字 ID
        profile = get_page_profile(page_id=page_id) or {}
        # 最终确认使用的数字 Page ID
        canonical_page_id = str(profile.get("page_id") or page_id)

        stats = {"replied": 0, "skipped": 0}

        # 递归处理所有评论
        async def _process_recursive(current_comment: dict[str, Any], depth: int, parent_msg: str = ""):
            # 1. 基础处理：尝试回复当前评论
            replied, skipped = await self._process_comment(
                current_comment,
                post,
                profile,
                monitor_id,
                facebook=facebook,
                ai=ai,
                depth=depth,
                parent_message=parent_msg,
                canonical_page_id=canonical_page_id
            )
            stats["replied"] += replied
            stats["skipped"] += skipped

            # 2. 持续处理：即使深度很大，只要有回复就继续向下处理
            replies = current_comment.get("replies", {}).get("data", [])
            for reply in replies:
                await _process_recursive(reply, depth + 1, current_comment.get("message", ""))

        # 开始遍历顶层评论
        for comment in comments:
            await _process_recursive(comment, 1)

        status_msg = f"OK: 已回复 {stats['replied']} 条，已跳过 {stats['skipped']} 条"
        finished_at = datetime.now().astimezone()
        update_monitor(
            monitor_id,
            last_run_at=finished_at.astimezone(timezone.utc).isoformat(),
            last_run_status=status_msg,
        )
        logger.info(
            "[%s] [monitor] monitor=%s done: %s",
            finished_at.strftime("%Y-%m-%d %H:%M:%S %z"),
            monitor_id,
            status_msg,
        )
        return stats

    async def _process_comment(
        self,
        comment: dict[str, Any],
        post: dict[str, Any],
        profile: dict[str, Any],
        monitor_id: int,
        *,
        facebook: FacebookService,
        ai: AIReplyService,
        depth: int,
        parent_message: str = "",
        canonical_page_id: str = ""
    ) -> tuple[int, int]:

        comment_id = comment.get("id", "")
        if not comment_id:
            return 0, 0

        # 1. 检查评论作者是否是主页自己 (防止自我回复)
        author = comment.get("from", {})
        author_id = str(author.get("id") or "")
        author_name = author.get("name", "")
        page_name = profile.get("name", "")

        if author_id and canonical_page_id and author_id == canonical_page_id:
            return 0, 0 # 是主页发的评论，不计入统计，直接跳过
        
        # 兜底：如果 ID 匹配不到，匹配名字 (防止某些 API 版本不返回 ID)
        if author_name and page_name and author_name == page_name:
            return 0, 0

        # 2. 检查主页是否已经回复过这条评论
        if has_replied(comment_id):
            still_has_page_reply = await self._comment_has_page_reply(
                comment=comment,
                page_id=canonical_page_id,
                facebook=facebook,
            )
            if still_has_page_reply:
                return 0, 1  # 已经回复过了，跳过

            # 本地记录已过期（回复可能被手动删了），清除记录允许重新回复
            try:
                unmark_replied(comment_id)
            except Exception:
                return 0, 1

        # 再次确认远程状态 (双重保险)
        if await self._comment_has_page_reply(comment=comment, page_id=canonical_page_id, facebook=facebook):
            return 0, 1

        # 3. 生成并发送回复
        comment_message = comment.get("message", "")
        try:
            reply_message = await ai.generate_reply(
                page_name=page_name,
                post_message=post.get("message", ""),
                comment_message=comment_message,
                comment_author=author_name or "匿名用户",
                parent_comment_message=parent_message,
            )
            await facebook.send_reply(comment_id, reply_message)
        except Exception as exc:
            logger.warning("[monitor] failed to reply to comment=%s: %s", comment_id, exc)
            return 0, 0

        # 4. 记录已回复
        try:
            mark_replied(comment_id, post.get("id", ""), monitor_id, reply_message)
        except Exception as exc:
            logger.warning("[monitor] reply sent but failed to persist record: %s", exc)

        logger.info("[monitor] replied to comment=%s author=%s depth=%s", comment_id, author_name, depth)
        return 1, 0

    async def _comment_has_page_reply(
        self,
        *,
        comment: dict[str, Any],
        page_id: str,
        facebook: FacebookService,
    ) -> bool:
        if not page_id:
            return True

        # Use replies from the current fetch first to avoid an extra request in common cases.
        for reply in comment.get("replies", {}).get("data", []):
            if str(reply.get("from", {}).get("id", "")) == page_id:
                return True

        comment_id = str(comment.get("id", ""))
        if not comment_id:
            return True

        try:
            latest_replies = await facebook.fetch_replies_for_comment(comment_id, limit=100)
        except Exception as exc:
            # Fail safe: if we cannot verify remote state, keep dedupe to avoid accidental spam.
            logger.warning(
                "[monitor] unable to verify existing replies for comment=%s: %s",
                comment_id,
                exc,
            )
            return True

        for reply in latest_replies:
            if str(reply.get("from", {}).get("id", "")) == page_id:
                return True

        return False
