from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import SESSION_COOKIE, authenticate_admin, create_session, is_authenticated
from app.config import PROJECT_ROOT, load_config
from app.repositories import list_comments_by_post_ids, list_monitors, list_posts, get_canonical_page_id
from app.repositories import cleanup_expired_admin_sessions, delete_admin_session
from app.security import SESSION_TTL_HOURS, generate_session_id

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    cleanup_expired_admin_sessions()
    if is_authenticated(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "next": next, "error": ""})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(""), next: str = Form("/")):
    cleanup_expired_admin_sessions()
    ok, message = authenticate_admin(password=password, request=request)
    if not ok:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "next": next, "error": message},
            status_code=401,
        )

    session_id = generate_session_id()
    create_session(session_id, request)

    safe_next = next if next.startswith("/") else "/"
    response = RedirectResponse(url=safe_next, status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=(request.url.scheme == "https"),
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE, "")
    if session_id:
        delete_admin_session(session_id)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@router.get("/comments", response_class=HTMLResponse)
async def content_page(request: Request, limit: int = 50):
    import json
    config = load_config()
    page_id = get_canonical_page_id(config.page_id)
    # 增加限制，避免一次性加载过多历史数据导致页面卡顿
    posts = list_posts(page_id=page_id, limit=limit)
    
    from app.repositories import list_monitored_post_ids
    monitored_post_ids = list_monitored_post_ids(page_id=page_id)

    from collections import defaultdict
    posts_by_date = defaultdict(list)

    for post in posts:
        msg = post.get("message") or ""
        post_data = {
            **post,
            "has_monitor": post["id"] in monitored_post_ids,
            "message_display": (msg[:300] + "...") if len(msg) > 300 else msg,
            # 初始加载不再包含所有评论，由前端按需异步加载
            "comments_count": 0, 
        }
        
        # 尝试从 raw_json 获取评论总数（如果存在）
        raw = post.get("raw_json")
        if raw:
            try:
                raw_data = json.loads(raw)
                # Facebook API 可能会在 post 对象中包含 comments 摘要
                comments_summary = raw_data.get("comments", {})
                summary = comments_summary.get("summary", {})
                post_data["comments_count"] = summary.get("total_count", 0)
            except Exception:
                pass

        date_str = "未知日期"
        if post.get("created_time"):
            try:
                date_str = post["created_time"].split("T")[0]
            except Exception:
                pass
        posts_by_date[date_str].append(post_data)

    sorted_dates = sorted(posts_by_date.keys(), reverse=True)
    grouped_posts = [{"date": d, "posts": posts_by_date[d]} for d in sorted_dates]

    return templates.TemplateResponse(
        "comments.html",
        {
            "request": request,
            "grouped_posts": grouped_posts,
            "current_limit": limit,
        },
    )


@router.get("/personas", response_class=HTMLResponse)
async def personas_page(request: Request):
    return templates.TemplateResponse("personas.html", {"request": request})

@router.get("/monitors", response_class=HTMLResponse)
async def monitors_page(request: Request):
    config = load_config()
    page_id = get_canonical_page_id(config.page_id)
    monitors = list_monitors(page_id=page_id)
    monitored_post_ids = {m["post_id"] for m in monitors}
    return templates.TemplateResponse(
        "monitors.html",
        {
            "request": request,
            "monitors": monitors,
            "monitored_post_ids": monitored_post_ids,
        },
    )
