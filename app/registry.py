"""Holds application-wide service singletons to avoid circular imports."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.monitor import MonitorService

import time

_monitor_service: "MonitorService | None" = None
_task_statuses: dict[str, dict] = {}


def set_monitor_service(svc: "MonitorService") -> None:
    global _monitor_service
    _monitor_service = svc


def get_monitor_service() -> "MonitorService":
    if _monitor_service is None:
        raise RuntimeError("MonitorService not initialized")
    return _monitor_service


def update_task_status(task_name: str, status: dict) -> None:
    """Updates the global status for a named task (e.g., 'post_sync', 'chat_sync')."""
    status["updated_at"] = time.time()
    _task_statuses[task_name] = status


def get_task_status(task_name: str) -> dict | None:
    """Retrieves the status for a named task."""
    status = _task_statuses.get(task_name)
    if status:
        # Auto-expire tasks older than 10 minutes that are 'completed'
        if status.get("done") and (time.time() - status["updated_at"] > 600):
            del _task_statuses[task_name]
            return None
    return status
