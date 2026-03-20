from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.registry import get_monitor_service
from app.config import load_config
from app.repositories import (
    create_account,
    create_monitor,
    delete_account,
    delete_comment_local,
    delete_monitor,
    get_account_by_id,
    get_active_account,
    get_comment,
    get_insights,
    get_model_config,
    get_monitor,
    get_page_profile,
    get_post,
    list_monitors,
    list_accounts,
    list_posts,
    list_replied_for_monitor,
    set_active_account,
    update_monitor,
    update_account,
    upsert_model_config,
    get_canonical_page_id,
    get_admin_auth,
    update_admin_password,
    delete_all_admin_sessions,
)
from app.services.ai_reply import AIReplyService
from app.services.facebook import FacebookService
from app.services.sync import SyncService
from app.security import PBKDF2_ITERATIONS, generate_salt, hash_password, is_strong_password, verify_password

router = APIRouter(prefix="/api")


class ReplyPayload(BaseModel):
    message: str


class CreateMonitorPayload(BaseModel):
    post_id: str
    interval_seconds: int = 300


class UpdateMonitorPayload(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None


class AccountPayload(BaseModel):
    name: str = ""
    page_access_token: str
    verify_token: str
    page_id: str
    api_version: str = "v25.0"


class ModelConfigPayload(BaseModel):
    ai_api_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""


class ChangePasswordPayload(BaseModel):
    old_password: str
    new_password: str


def _assert_monitor_belongs_to_active_page(monitor: dict) -> None:
    config = load_config()
    page_id = get_canonical_page_id(config.page_id)
    monitor_page_id = str(monitor.get("page_id", ""))
    if monitor_page_id != page_id:
        raise HTTPException(status_code=404, detail="监控不存在")


@router.get("/settings")
async def get_settings():
    accounts = list_accounts()
    active = get_active_account()
    model = get_model_config() or {
        "ai_api_base_url": "",
        "ai_api_key": "",
        "ai_model": "",
    }
    return {
        "accounts": accounts,
        "active_account_id": active["id"] if active else None,
        "model": model,
    }


@router.post("/settings/accounts")
async def create_account_api(payload: AccountPayload):
    page_id = payload.page_id.strip()
    token = payload.page_access_token.strip()
    verify = payload.verify_token.strip()
    if not page_id or not token or not verify:
        raise HTTPException(status_code=400, detail="PAGE_ID、PAGE_ACCESS_TOKEN、VERIFY_TOKEN 不能为空")

    try:
        account_id = create_account(
            name=payload.name.strip() or f"账号 {page_id}",
            page_access_token=token,
            verify_token=verify,
            page_id=page_id,
            api_version=(payload.api_version.strip() or "v25.0"),
            is_active=0,
        )
        return {"status": "success", "account_id": account_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"保存账号失败: {exc}") from exc


@router.put("/settings/accounts/{account_id}")
async def update_account_api(account_id: int, payload: AccountPayload):
    account = get_account_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    page_id = payload.page_id.strip()
    token = payload.page_access_token.strip()
    verify = payload.verify_token.strip()
    if not page_id or not token or not verify:
        raise HTTPException(status_code=400, detail="PAGE_ID、PAGE_ACCESS_TOKEN、VERIFY_TOKEN 不能为空")

    try:
        update_account(
            account_id,
            name=payload.name.strip() or f"账号 {page_id}",
            page_access_token=token,
            verify_token=verify,
            page_id=page_id,
            api_version=(payload.api_version.strip() or "v25.0"),
        )
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"更新账号失败: {exc}") from exc


@router.post("/settings/accounts/{account_id}/activate")
async def activate_account_api(account_id: int):
    account = get_account_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    set_active_account(account_id)
    return {"status": "success"}


@router.delete("/settings/accounts/{account_id}")
async def delete_account_api(account_id: int):
    account = get_account_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    delete_account(account_id)
    return {"status": "success"}


@router.get("/settings/accounts/export")
async def export_accounts_api():
    accounts = list_accounts()
    # Remove sensitive/internal fields if needed, but for "batch import/export" we keep tokens
    export_data = []
    for acc in accounts:
        export_data.append({
            "name": acc["name"],
            "page_id": acc["page_id"],
            "page_access_token": acc["page_access_token"],
            "verify_token": acc["verify_token"],
            "api_version": acc["api_version"],
        })
    return export_data


@router.post("/settings/accounts/import")
async def import_accounts_api(payload: list[dict]):
    try:
        from app.repositories import bulk_import_accounts
        count = bulk_import_accounts(payload)
        return {"status": "success", "count": count}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入失败: {exc}")


@router.put("/settings/model")
async def update_model_api(payload: ModelConfigPayload):
    upsert_model_config(
        ai_api_base_url=payload.ai_api_base_url.strip(),
        ai_api_key=payload.ai_api_key.strip(),
        ai_model=payload.ai_model.strip(),
    )
    return {"status": "success"}


@router.post("/settings/model/test")
async def test_model_api(payload: ModelConfigPayload):
    from app.config import AppConfig
    # Use the payload values instead of saved config for testing
    temp_config = AppConfig(
        account_id=0,
        account_name="",
        page_access_token="",
        verify_token="",
        page_id="",
        ai_api_base_url=payload.ai_api_base_url.strip(),
        ai_api_key=payload.ai_api_key.strip(),
        ai_model=payload.ai_model.strip(),
        # Other fields don't matter for this test
    )
    ai_service = AIReplyService(temp_config)
    try:
        result = await ai_service.test_connection()
        return {"status": "success", "message": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/change-password")
async def change_admin_password(payload: ChangePasswordPayload):
    auth = get_admin_auth()
    if auth is None:
        raise HTTPException(status_code=500, detail="管理员账号不存在")

    old_ok = verify_password(
        payload.old_password,
        salt_hex=str(auth.get("password_salt", "")),
        expected_hash_hex=str(auth.get("password_hash", "")),
        iterations=int(auth.get("password_iterations", PBKDF2_ITERATIONS)),
    )
    if not old_ok:
        raise HTTPException(status_code=400, detail="旧密码错误")

    if not is_strong_password(payload.new_password):
        raise HTTPException(status_code=400, detail="新密码不符合强密码要求（至少16位，包含大小写字母、数字和符号）")

    salt = generate_salt()
    pwd_hash = hash_password(payload.new_password, salt, PBKDF2_ITERATIONS)
    update_admin_password(
        password_hash=pwd_hash,
        password_salt=salt,
        password_iterations=PBKDF2_ITERATIONS,
    )

    delete_all_admin_sessions()
    return {"status": "success", "message": "密码已更新，请重新登录"}


# ---------------------------------------------------------------------------
# Page profile
# ---------------------------------------------------------------------------

@router.get("/page-profile")
async def page_profile():
    config = load_config()
    profile = get_page_profile(page_id=config.page_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="尚未同步到主页信息")
    return profile


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post("/sync")
async def sync_data(limit: int = 20, since: str = "", until: str = ""):
    config = load_config()
    service = SyncService(config)
    try:
        return {"status": "success", "summary": await service.sync_all(post_limit=limit, since=since, until=until)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sync-insights")
async def sync_insights_api():
    config = load_config()
    service = SyncService(config)
    try:
        return {"status": "success", "summary": await service.sync_insights()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

@router.get("/insights/page")
async def page_insights_api():
    config = load_config()
    page_id = get_canonical_page_id(config.page_id)
    return {"data": get_insights(page_id)}


@router.get("/insights/{target_id:path}")
async def target_insights_api(target_id: str):
    return {"data": get_insights(target_id)}


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@router.post("/comments/{comment_id}/reply")
async def create_reply(comment_id: str, payload: ReplyPayload):
    config = load_config()
    facebook = FacebookService(config)
    sync_service = SyncService(config)
    try:
        await facebook.send_reply(comment_id, payload.message)
        summary = await sync_service.sync_all()
        return {"status": "success", "summary": summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/comments/{comment_id}/ai-reply")
async def create_ai_reply(comment_id: str):
    config = load_config()
    comment = get_comment(comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="评论不存在")

    post = get_post(comment["post_id"])
    if post is None:
        raise HTTPException(status_code=404, detail="评论所属帖子不存在")

    profile = get_page_profile(page_id=config.page_id) or {}
    ai_service = AIReplyService(config)
    try:
        message = await ai_service.generate_reply(
            page_name=profile.get("name", ""),
            post_message=post.get("message", ""),
            comment_message=comment.get("message", ""),
            comment_author=comment.get("author_name", "匿名用户"),
        )
        return {"status": "success", "message": message}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/comments/{comment_id}")
async def remove_comment(comment_id: str):
    config = load_config()
    facebook = FacebookService(config)
    try:
        deleted = await facebook.delete_comment(comment_id)
        if not deleted:
            raise HTTPException(status_code=500, detail="Facebook 未确认删除成功")
        delete_comment_local(comment_id)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Posts (for monitor creation form)
# ---------------------------------------------------------------------------

@router.get("/posts")
async def list_posts_api():
    config = load_config()
    page_id = get_canonical_page_id(config.page_id)
    posts = list_posts(page_id=page_id)
    monitors = {m["post_id"]: m for m in list_monitors(page_id=page_id)}
    result = []
    for post in posts:
        item = {
            "id": post["id"],
            "message": post.get("message", ""),
            "created_time": post.get("created_time", ""),
            "permalink_url": post.get("permalink_url", ""),
            "has_monitor": post["id"] in monitors,
        }
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Monitors
# ---------------------------------------------------------------------------

@router.get("/monitors")
async def list_monitors_api():
    config = load_config()
    page_id = get_canonical_page_id(config.page_id)
    return list_monitors(page_id=page_id)


@router.post("/monitors")
async def create_monitor_api(payload: CreateMonitorPayload):
    post = get_post(payload.post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="帖子不存在，请先同步数据")
    try:
        monitor_id = create_monitor(
            post_id=payload.post_id,
            interval_seconds=max(1, payload.interval_seconds),
        )
        return {"status": "success", "monitor_id": monitor_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/monitors/{monitor_id}")
async def get_monitor_api(monitor_id: int):
    monitor = get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="监控不存在")
    _assert_monitor_belongs_to_active_page(monitor)
    return monitor


@router.patch("/monitors/{monitor_id}")
async def update_monitor_api(monitor_id: int, payload: UpdateMonitorPayload):
    monitor = get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="监控不存在")
    _assert_monitor_belongs_to_active_page(monitor)
    kwargs: dict = {}
    if payload.enabled is not None:
        kwargs["enabled"] = int(payload.enabled)
    if payload.interval_seconds is not None:
        kwargs["interval_seconds"] = max(1, payload.interval_seconds)
    update_monitor(monitor_id, **kwargs)
    return {"status": "success"}


@router.delete("/monitors/{monitor_id}")
async def delete_monitor_api(monitor_id: int):
    monitor = get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="监控不存在")
    _assert_monitor_belongs_to_active_page(monitor)
    delete_monitor(monitor_id)
    return {"status": "success"}


@router.post("/monitors/{monitor_id}/run")
async def run_monitor_now_api(monitor_id: int):
    monitor = get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="监控不存在")
    _assert_monitor_belongs_to_active_page(monitor)
    try:
        svc = get_monitor_service()
        result = await svc.run_monitor_now(monitor_id)
        return {"status": "success", "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/monitors/{monitor_id}/replied")
async def list_replied_api(monitor_id: int, limit: int = 50):
    monitor = get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="监控不存在")
    _assert_monitor_belongs_to_active_page(monitor)
    return list_replied_for_monitor(monitor_id, limit=limit)
