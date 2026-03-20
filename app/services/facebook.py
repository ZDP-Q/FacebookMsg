from __future__ import annotations

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

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                params=merged_params,
                json=json_body,
            )

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

    async def fetch_page_insights(self) -> list[dict[str, Any]]:
        metrics = [
            "page_impressions",
            "page_media_view",
            "page_total_media_view_unique",
            "page_engaged_users",
            "page_views_total",
            "page_post_engagements",
            "page_actions_post_reactions_total",
        ]
        return await self._fetch_insights_by_metrics(
            path=f"{self.config.page_id}/insights",
            metrics=metrics,
            period="days_28",
        )

    async def fetch_post_insights(self, post_id: str) -> list[dict[str, Any]]:
        metrics = [
            "post_impressions",
            "post_media_view",
            "post_total_media_view_unique",
            "post_engaged_users",
            "post_clicks",
            "post_reactions_like_total",
        ]
        return await self._fetch_insights_by_metrics(
            path=f"{post_id}/insights",
            metrics=metrics,
            period="lifetime",
        )

    async def fetch_video_insights(self, video_id: str) -> list[dict[str, Any]]:
        metric_candidates = [
            "total_video_views",
            "total_video_view_total_time",
            "total_video_complete_views",
        ]
        path_candidates = [
            f"{video_id}/insights",
            f"{video_id}/video_insights",
        ]

        merged: list[dict[str, Any]] = []
        for path in path_candidates:
            data = await self._fetch_insights_by_metrics(
                path=path,
                metrics=metric_candidates,
                period="lifetime",
            )
            if data:
                merged.extend(data)
                break
        return self._normalize_insights(self._dedupe_insights(merged))

    async def _fetch_insights_by_metrics(self, *, path: str, metrics: list[str], period: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        # Try batch querying first; if one metric is unsupported, fall back to per-metric requests.
        try:
            payload = await self._request(
                "GET",
                path,
                params={
                    "metric": ",".join(metrics),
                    "period": period,
                },
            )
            results.extend(payload.get("data", []))
            return self._normalize_insights(self._dedupe_insights(results))
        except Exception:
            pass

        for metric in metrics:
            try:
                payload = await self._request(
                    "GET",
                    path,
                    params={
                        "metric": metric,
                        "period": period,
                    },
                )
                results.extend(payload.get("data", []))
            except Exception:
                # Different pages/posts expose different metrics. Ignore unsupported ones.
                continue
        return self._normalize_insights(self._dedupe_insights(results))

    def _dedupe_insights(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for item in data:
            name = str(item.get("name", ""))
            if name:
                deduped[name] = item
        return list(deduped.values())

    def _normalize_insights(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize insights values to numeric-friendly shapes for UI rendering.

        Some v25 metrics can return structured objects in `values[].value`.
        """
        normalized: list[dict[str, Any]] = []
        for item in data:
            cloned = dict(item)
            values = cloned.get("values")

            if not values and "total_value" in cloned:
                total_value = cloned.get("total_value")
                value_num = self._extract_numeric_value(total_value)
                if value_num is not None:
                    cloned["values"] = [{"value": value_num}]
                    normalized.append(cloned)
                    continue

            if isinstance(values, list):
                norm_values: list[dict[str, Any]] = []
                for value_item in values:
                    if isinstance(value_item, dict):
                        v = value_item.get("value")
                        if isinstance(v, dict):
                            value_item = dict(value_item)
                            value_item["value"] = self._extract_numeric_value(v)
                    norm_values.append(value_item)
                cloned["values"] = norm_values

            normalized.append(cloned)

        return normalized

    def _extract_numeric_value(self, value: Any) -> int | float | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, dict):
            total: float = 0
            found = False
            for nested in value.values():
                extracted = self._extract_numeric_value(nested)
                if extracted is not None:
                    total += float(extracted)
                    found = True
            if found:
                return int(total) if total.is_integer() else total
        if isinstance(value, list):
            total: float = 0
            found = False
            for nested in value:
                extracted = self._extract_numeric_value(nested)
                if extracted is not None:
                    total += float(extracted)
                    found = True
            if found:
                return int(total) if total.is_integer() else total
        return None
