from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import AppConfig
from app.repositories import replace_comments_for_post, upsert_page_profile, upsert_post, list_posts, get_canonical_page_id
from app.services.facebook import FacebookService
from app.registry import update_task_status


logger = logging.getLogger("uvicorn.error")


class SyncService:
    def __init__(self, config: AppConfig):
        self.facebook = FacebookService(config)
        self.config = config

    async def sync_all(self, *, post_limit: int = 20, since: str = "", until: str = "", all_posts: bool = False) -> dict[str, Any]:
        """Wrapper around sync_all_gen for backward compatibility."""
        final_result = {}
        async for step in self.sync_all_gen(post_limit=post_limit, since=since, until=until, all_posts=all_posts):
            if "status" in step and step["status"] == "completed":
                final_result = step.get("result", {})
        return final_result

    async def sync_all_gen(self, *, post_limit: int = 20, since: str = "", until: str = "", all_posts: bool = False):
        """Progress generator for SSE. It starts the background worker if not already running."""
        from app.registry import get_task_status
        current = get_task_status("post_sync")
        
        if not current or current.get("done"):
            asyncio.create_task(self._run_sync_worker(post_limit, since, until, all_posts))
            await asyncio.sleep(0.1)

        last_update = 0
        while True:
            status = get_task_status("post_sync")
            if not status: break
            
            if status.get("updated_at", 0) > last_update:
                yield status
                last_update = status.get("updated_at", 0)
            
            if status.get("done"): break
            await asyncio.sleep(1)

    async def _run_sync_worker(self, post_limit: int, since: str, until: str, all_posts: bool):
        if self.config.page_id == "default-page":
            logger.warning("[sync] Skipping sync for 'default-page'.")
            update_task_status("post_sync", {"msg": "跳过默认页面", "done": True, "percent": 0})
            return

        try:
            update_task_status("post_sync", {"msg": "正在获取主页基本信息...", "percent": 5, "done": False})
            profile = await self.facebook.fetch_page_profile()
            upsert_page_profile(profile)
            
            canonical_page_id = str(profile.get("id", ""))
            normalized_all_posts = all_posts or post_limit <= 0
            
            status_msg = f"正在获取帖子列表 (limit={post_limit if not normalized_all_posts else '全部'})..."
            update_task_status("post_sync", {"msg": status_msg, "percent": 15, "done": False})
            
            raw_posts, next_cursor = await self._fetch_posts_for_sync(
                canonical_page_id=canonical_page_id,
                post_limit=post_limit,
                since=since,
                until=until,
                all_posts=normalized_all_posts,
            )
            
            posts = []
            for post in raw_posts:
                if self._is_post_from_current_page(post, canonical_page_id):
                    posts.append(post)

            total_posts = len(posts)
            if not posts:
                update_task_status("post_sync", {"msg": "同步完成，未发现新帖子", "percent": 100, "done": True})
                return

            status_msg = f"发现 {total_posts} 篇帖子，开始同步媒体信息和评论..."
            update_task_status("post_sync", {"msg": status_msg, "percent": 25, "done": False})

            synced_comment_count = 0
            batch_size = 5
            processed_count = 0

            for i in range(0, total_posts, batch_size):
                batch = posts[i : i + batch_size]
                await asyncio.gather(*[self._sync_post_media(canonical_page_id, p) for p in batch])
                counts = await asyncio.gather(*[self._sync_post_comments(p) for p in batch])
                synced_comment_count += sum(counts)
                
                processed_count += len(batch)
                percent = 25 + int((processed_count / total_posts) * 70)
                status_msg = f"已处理 {processed_count}/{total_posts} 篇帖子..."
                update_task_status("post_sync", {"msg": status_msg, "percent": percent, "done": False})

            update_task_status("post_sync", {
                "msg": "同步完成！", 
                "percent": 100, 
                "done": True,
                "result": {
                    "page_id": canonical_page_id,
                    "post_count": total_posts,
                    "comment_count": synced_comment_count,
                    "next_cursor": next_cursor,
                    "all_posts": normalized_all_posts,
                }
            })
        except Exception as e:
            logger.error("[sync] Background worker failed: %s", e, exc_info=True)
            update_task_status("post_sync", {"msg": f"同步失败: {str(e)}", "done": True, "error": True})

    async def sync_post(self, post_id: str) -> dict[str, Any]:
        if self.config.page_id == "default-page":
            logger.warning("[sync_post] Skipping sync for 'default-page' as it is a placeholder.")
            return {"status": "skipped", "reason": "default-page"}
        
        logger.info("[sync] start syncing single post=%s", post_id)
        profile = await self.facebook.fetch_page_profile()
        upsert_page_profile(profile)
        canonical_page_id = str(profile.get("id", ""))

        post = await self.facebook.fetch_post(post_id)
        if not self._is_post_from_current_page(post, canonical_page_id):
            raise RuntimeError("目标帖子不属于当前主页，已拒绝同步")

        await self._sync_post_media(canonical_page_id, post)
        comment_count = await self._sync_post_comments(post)

        logger.info("[sync] single post synced: post=%s comments=%s", post_id, comment_count)
        return {
            "page_id": canonical_page_id or self.config.page_id,
            "post_id": post_id,
            "comment_count": comment_count,
        }

    def _is_post_from_current_page(self, post: dict[str, Any], canonical_page_id: str) -> bool:
        # 如果存在 from 字段且 id 明确，直接使用 from 来判断是不是主页自己的帖子
        from_id = post.get("from", {}).get("id")
        if from_id:
            if from_id == canonical_page_id or from_id == self.config.page_id:
                return True
            # 如果是有明确来源但不是本主页，则说明是其他人发在主页上的帖子（例如 feed 接口返回的）
            return False

        post_id = str(post.get("id", ""))
        # Facebook post ids usually look like "{page_id}_{post_id}".
        if "_" in post_id:
            prefix = post_id.split("_", 1)[0]
            # 匹配逻辑：帖子前缀匹配规范化 ID 或配置中的 ID
            return prefix == canonical_page_id or prefix == self.config.page_id
        
        # 若是其他格式ID（无下划线），由于现在我们请求了 'posts' 边缘，通常都是直接合法的帖子放行
        return True

    async def _fetch_posts_for_sync(
        self,
        *,
        canonical_page_id: str,
        post_limit: int,
        since: str,
        until: str,
        all_posts: bool,
    ) -> tuple[list[dict[str, Any]], str]:
        if not all_posts:
            result = await self.facebook.fetch_posts(
                limit=max(1, post_limit),
                since=since,
                until=until,
                page_id=canonical_page_id,
            )
            return result.get("data", []), result.get("paging", {}).get("cursors", {}).get("after", "")

        all_raw_posts: list[dict[str, Any]] = []
        cursor = ""
        while True:
            result = await self.facebook.fetch_posts(
                limit=100,
                since=since,
                until=until,
                after=cursor,
                page_id=canonical_page_id,
            )
            batch = result.get("data", [])
            all_raw_posts.extend(batch)

            paging = result.get("paging", {})
            cursor = paging.get("cursors", {}).get("after", "")
            has_next = bool(paging.get("next")) and bool(cursor)
            if not has_next or not batch:
                break

        return all_raw_posts, cursor

    async def _sync_post_media(self, canonical_page_id: str, post: dict[str, Any]) -> None:
        try:
            media_info = await self.facebook.fetch_post_media_info(post["id"])
            post["type"] = media_info.get("type", "")
            if media_info.get("target_id"):
                post["video_id"] = media_info["target_id"]
        except Exception as exc:
            logger.warning("[sync] failed to detect media type for post=%s: %s", post.get("id", ""), exc)
        upsert_post(canonical_page_id, post)

    async def _sync_post_comments(self, post: dict[str, Any]) -> int:
        post_id = post.get("id", "")
        try:
            comments = await self.facebook.fetch_comments_for_post(post_id, limit=200)
            replace_comments_for_post(post_id, comments)
            count = sum(self._count_comment_tree(c) for c in comments)
            logger.info("[sync] comments synced for post=%s top_level=%s total=%s", post_id, len(comments), count)
            return count
        except Exception as exc:
            logger.error("[sync] failed to sync comments for post=%s: %s", post_id, exc)
            return 0

    def _count_comment_tree(self, comment: dict[str, Any]) -> int:
        replies = comment.get("replies", {}).get("data", [])
        return 1 + sum(self._count_comment_tree(reply) for reply in replies)

    async def _run_in_batches(self, coroutines: list[Any], batch_size: int = 8) -> list[Any]:
        results: list[Any] = []
        for idx in range(0, len(coroutines), batch_size):
            batch = coroutines[idx : idx + batch_size]
            results.extend(await asyncio.gather(*batch))
        return results
