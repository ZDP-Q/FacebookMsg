from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from app.services.facebook import FacebookService
from app.repositories import (
    upsert_page_conversation, 
    bulk_upsert_conversation_messages,
    get_latest_conversation_update,
    get_latest_message_time
)

from app.registry import update_task_status

logger = logging.getLogger("uvicorn.error")

class ChatSyncService:
    def __init__(self, fb_service: FacebookService):
        self.fb = fb_service
        self.semaphore = asyncio.Semaphore(5)  # Max 5 concurrent conversation fetches
        self.messages_synced = 0
        self.conversations_synced = 0

    async def sync_all_chats(self, page_id: str, full_sync: bool = False) -> AsyncGenerator[str, None]:
        """Progress generator for SSE. It starts the background worker if not already running."""
        from app.registry import get_task_status
        current = get_task_status("chat_sync")
        
        if not current or current.get("done"):
            asyncio.create_task(self._run_sync_worker(page_id, full_sync))
            await asyncio.sleep(0.1)

        last_update = 0
        while True:
            status = get_task_status("chat_sync")
            if not status:
                break
                
            if status.get("updated_at", 0) > last_update:
                yield "event: progress\ndata: " + json.dumps(status) + "\n\n"
                last_update = status.get("updated_at", 0)
            
            if status.get("done"):
                break
            
            await asyncio.sleep(1)

    async def _run_sync_worker(self, page_id: str, full_sync: bool):
        """The actual background worker performing the sync in two phases."""
        since_conv = ""
        if not full_sync:
            since_conv = get_latest_conversation_update(page_id) or ""
            logger.info("[chat_sync] Incremental sync since: %s", since_conv)
        else:
            logger.info("[chat_sync] FORCING FULL SYNC - Scanning all folders for Page: %s", page_id)
        
        status_msg = "阶段 1/2: 正在扫描会话列表..."
        update_task_status("chat_sync", {"msg": status_msg, "percent": 5, "done": False})
        
        self.conversations_synced = 0
        self.messages_synced = 0
        discovered_conv_set = set()
        
        target = page_id or "me"
        # We scan multiple folders to ensure maximum coverage
        folders = ["inbox", "archive", "other", "spam"] if full_sync else ["inbox"]
        
        try:
            # --- Phase 1: Discovery ---
            for folder in folders:
                after = ""
                folder_count = 0
                logger.info("[chat_sync] Phase 1 - Scanning folder: %s", folder)
                
                while True:
                    params = {
                        "fields": "id,updated_time,unread_count,participants",
                        "limit": 100,
                        "folder": folder
                    }
                    if after: params["after"] = after
                    if since_conv: params["since"] = since_conv
                    
                    payload = await self.fb._request('GET', f"{target}/conversations", params=params)
                    data = payload.get("data", [])
                    if not data:
                        break

                    for conv in data:
                        conv_id = conv["id"]
                        if conv_id not in discovered_conv_set:
                            discovered_conv_set.add(conv_id)
                            folder_count += 1
                            upsert_page_conversation(
                                conv_id=conv_id,
                                page_id=page_id,
                                updated_time=conv.get("updated_time"),
                                unread_count=conv.get("unread_count", 0),
                                participants_json=json.dumps(conv.get("participants", {}))
                            )
                    
                    update_task_status("chat_sync", {
                        "msg": f"阶段 1: 扫描目录 [{folder}] - 已发现 {len(discovered_conv_set)} 个会话...",
                        "percent": 10,
                        "done": False
                    })

                    paging = payload.get("paging", {})
                    after = paging.get("cursors", {}).get("after")
                    if not after:
                        break
            
            discovered_conv_ids = list(discovered_conv_set)
            total_convs = len(discovered_conv_ids)
            logger.info("[chat_sync] Phase 1 complete. Unique conversations found: %d", total_convs)
            
            if total_convs == 0:
                update_task_status("chat_sync", {"msg": "没有发现需要同步的新会话。", "percent": 100, "done": True})
                return

            # --- Phase 2: Message Sync ---
            status_msg = f"阶段 2/2: 正在拉取 {total_convs} 个会话的消息内容..."
            update_task_status("chat_sync", {"msg": status_msg, "percent": 20, "done": False})
            
            pending = {
                asyncio.create_task(self._sync_messages_task(conv_id, full_sync=full_sync))
                for conv_id in discovered_conv_ids
            }
            
            while pending:
                done, pending = await asyncio.wait(pending, timeout=1.0, return_when=asyncio.FIRST_COMPLETED)
                processed = self.conversations_synced
                percent = 20 + int((processed / total_convs) * 80)
                update_task_status("chat_sync", {
                    "msg": f"正在拉取消息: {processed}/{total_convs} 会话...",
                    "messages_synced": self.messages_synced,
                    "percent": min(99, percent),
                    "done": False
                })
            
            final_msg = f"同步完成！共处理 {total_convs} 个会话，新增/更新 {self.messages_synced} 条消息。"
            update_task_status("chat_sync", {
                "msg": final_msg, 
                "done": True, 
                "conversations": self.conversations_synced, 
                "messages": self.messages_synced, 
                "percent": 100
            })
            
        except Exception as e:
            logger.error("[chat_sync] background worker failed: %s", e, exc_info=True)
            update_task_status("chat_sync", {"msg": f"同步失败: {str(e)}", "done": True, "error": True})

    async def _sync_messages_task(self, conv_id: str, full_sync: bool):
        async with self.semaphore:
            msg_count = await self._sync_messages_for_conversation(conv_id, full_sync=full_sync)
            self.messages_synced += msg_count
            self.conversations_synced += 1

    async def _sync_messages_for_conversation(self, conv_id: str, full_sync: bool) -> int:
        count = 0
        after = ""
        since_msg = ""
        if not full_sync:
            since_msg = get_latest_message_time(conv_id) or ""
            
        while True:
            try:
                payload = await self.fb.fetch_messages(conv_id, limit=100, after=after, since=since_msg)
                data = payload.get("data", [])
                if not data:
                    break
                
                batch_messages = []
                for msg in data:
                    text = self._filter_message_content(msg)
                    sender = msg.get("from", {})
                    batch_messages.append((
                        msg["id"], conv_id, text, sender.get("id"), sender.get("name"), msg.get("created_time")
                    ))
                    count += 1
                
                if batch_messages:
                    bulk_upsert_conversation_messages(batch_messages)
                    
                paging = payload.get("paging", {})
                after = paging.get("cursors", {}).get("after")
                if not after:
                    break
            except Exception as e:
                logger.warning("[chat_sync] Failed to fetch messages for %s: %s", conv_id, e)
                break
        return count

    def _filter_message_content(self, msg: dict) -> str:
        text = msg.get("message", "")
        if msg.get("sticker"):
            text = text + " [表情]" if text else "[表情]"
        attachments = msg.get("attachments", {}).get("data", [])
        for att in attachments:
            mime = att.get("mime_type", "") or ""
            if "image" in mime: text += " [图片]"
            elif "audio" in mime or "voice" in mime: text += " [语音]"
            elif "video" in mime: text += " [视频]"
            else: text += " [文件]"
        return text.strip()
