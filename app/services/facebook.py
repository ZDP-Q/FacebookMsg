from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import AppConfig


class FacebookService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.base_url = config.graph_base_url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        merged_params = {"access_token": self.config.page_access_token}
        if params:
            merged_params.update(params)

        response: httpx.Response | None = None
        last_exc: Exception | None = None

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}/{path.lstrip('/')}",
                        params=merged_params,
                        json=json_body,
                    )

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                break
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(1.0 * (2 ** attempt))
                    continue
                break

        if response is None:
            raise RuntimeError(f"Facebook API 请求失败：{last_exc or '未收到响应'}")

        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise RuntimeError(detail)

        if not response.content:
            return None
        return response.json()

    async def fetch_page_profile(self) -> dict[str, Any]:
        return await self._request(
            "GET",
            self.config.page_id,
            params={
                "fields": "id,name,username,link,fan_count,category,picture.width(200).height(200){url}",
            },
        )

    async def fetch_posts(self, limit: int = 20, since: str = "", until: str = "", after: str = "", page_id: str | None = None) -> dict[str, Any]:
        """Fetch posts with optional time range and pagination.
        Args:
            limit: Max posts per request (max 100 per Facebook API).
            since: Unix timestamp or date string (ISO 8601) for start range.
            until: Unix timestamp or date string (ISO 8601) for end range.
            after: Cursor for pagination to fetch next batch.
            page_id: Explicit page ID to use. If omitted, uses 'me' which is recommended for Page Tokens.
        Returns:
            dict with 'data' (list of posts) and 'paging' (cursor info).
        """
        limit = min(limit, 100)
        params = {
            "fields": "id,message,created_time,permalink_url,from",
            "limit": limit,
        }
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if after:
            params["after"] = after

        # 在 v25.0 中，使用 Page Access Token 时，请求 /me 是最可靠的。
        # 如果提供了 page_id (数字 ID)，则优先使用，否则使用 me。
        target = page_id or "me"

        import logging
        logger = logging.getLogger("uvicorn.error")

        # v25.0 下，优先读取发布帖流，避免把 feed 中访客帖与主页帖混在一起后再截断，
        # 否则可能出现“同样 limit 下新帖被挤出结果集”的问题。
        edge_plan: list[tuple[str, dict[str, Any]]] = [
            ("published_posts", dict(params)),
            ("posts", dict(params)),
            ("feed", {**params, "is_published": "true"}),
        ]

        errors: list[str] = []
        for edge, edge_params in edge_plan:
            try:
                payload = await self._request(
                    "GET",
                    f"{target}/{edge}",
                    params=edge_params,
                )
                data = payload.get("data", [])
                logger.info("[facebook] fetched %s posts from edge: %s (target: %s)", len(data), edge, target)

                if data:
                    data.sort(key=lambda item: self._parse_fb_time(item.get("created_time", "")), reverse=True)
                    return {
                        "data": data[:limit],
                        "paging": payload.get("paging", {}),
                    }
            except Exception as exc:
                # 某些 edge 可能因权限或主页类型不可用，回退到下一个 edge
                logger.debug("[facebook] edge %s not available for %s: %s", edge, target, exc)
                errors.append(f"{edge}: {exc}")
                continue

        if errors:
            raise RuntimeError(f"无法从页面帖子相关 Edge 获取数据。报错信息: {'; '.join(errors)}")

        return {"data": [], "paging": {}}

    def _parse_fb_time(self, value: str) -> float:
        raw = str(value or "").strip()
        if not raw:
            return 0.0

        # Facebook often returns +0000 timezone style, normalize to ISO +00:00.
        if len(raw) >= 5 and (raw[-5] in "+-") and raw[-3] != ":":
            raw = f"{raw[:-2]}:{raw[-2:]}"

        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return 0.0

    async def fetch_post_media_info(self, post_id: str) -> dict[str, str]:
        payload = await self._request(
            "GET",
            post_id,
            params={
                "fields": "attachments{media_type,target{id}}",
            },
        )

        media_type = ""
        media_target_id = ""
        attachments = payload.get("attachments", {}).get("data", [])
        if attachments:
            first = attachments[0]
            media_type = str(first.get("media_type", "")).lower()
            media_target_id = str(first.get("target", {}).get("id", ""))

        return {
            "type": media_type,
            "target_id": media_target_id,
        }

    async def fetch_post(self, post_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            post_id,
            params={"fields": "id,message,created_time,permalink_url"},
        )

    async def fetch_comments_for_post(self, post_id: str, limit: int = 100) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            f"{post_id}/comments",
            params={
                "fields": "id,message,from,created_time,parent{id}",
                "limit": limit,
            },
        )
        comments = payload.get("data", [])
        for comment in comments:
            await self._populate_replies(comment, limit=limit, depth=1, max_depth=20)
        return comments

    async def fetch_replies_for_comment(self, comment_id: str, limit: int = 100) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            f"{comment_id}/comments",
            params={
                "fields": "id,message,from,created_time,parent{id}",
                "limit": limit,
            },
        )
        return payload.get("data", [])

    async def _populate_replies(
        self,
        comment: dict[str, Any],
        *,
        limit: int,
        depth: int,
        max_depth: int,
    ) -> None:
        comment_id = str(comment.get("id", ""))
        if not comment_id or depth >= max_depth:
            return

        replies = await self.fetch_replies_for_comment(comment_id, limit=limit)
        if not replies:
            return

        comment["replies"] = {"data": replies}
        for reply in replies:
            await self._populate_replies(reply, limit=limit, depth=depth + 1, max_depth=max_depth)

    async def send_reply(self, comment_id: str, message: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"{comment_id}/comments",
            json_body={"message": message},
        )

    async def delete_comment(self, comment_id: str) -> bool:
        result = await self._request("DELETE", comment_id)
        return bool(result)

