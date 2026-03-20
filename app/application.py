from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import SESSION_COOKIE, is_authenticated
from app.config import PROJECT_ROOT
from app.database import init_db, migrate_legacy_json_if_needed
from app.registry import set_monitor_service
from app.routes.api import router as api_router
from app.routes.webhook import router as webhook_router
from app.routes.web import router as web_router
from app.services.monitor import MonitorService


logger = logging.getLogger("uvicorn.error")


def _is_public_path(path: str) -> bool:
    if path in {"/login", "/favicon.ico"}:
        return True
    if path.startswith("/static/"):
        return True
    # Webhook 需要保持可被 Facebook 回调
    if path.startswith("/webhook"):
        return True
    return False

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate_legacy_json_if_needed()
    svc = MonitorService()
    set_monitor_service(svc)
    await svc.start()
    logger.info("[startup] database initialized; monitor scheduler started")
    try:
        yield
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await svc.stop()
        logger.info("[shutdown] monitor scheduler stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=lifespan,
        title="FBIManager",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        path = request.url.path
        host = request.headers.get("host", "")
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        
        # 适配反向代理后的协议识别
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        origin_base = f"{forwarded_proto}://{host}" if host else ""

        if not _is_public_path(path):
            session_id = request.cookies.get(SESSION_COOKIE)
            if not is_authenticated(session_id):
                if path.startswith("/api"):
                    return JSONResponse({"detail": "未登录或会话已过期"}, status_code=401)
                next_path = quote(path, safe="/?=&")
                return RedirectResponse(url=f"/login?next={next_path}", status_code=303)

            # 登录态下对敏感写操作做同源校验，降低 CSRF 风险
            if path.startswith("/api") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                if not origin_base and host:
                    origin_base = f"{forwarded_proto}://{host}"

                def _normalize(url_str: str) -> str:
                    # 移除协议头、末尾斜杠和默认端口，仅比较域名和有效端口
                    u = url_str.lower().rstrip("/")
                    if "://" in u:
                        u = u.split("://", 1)[1]
                    return u

                target = _normalize(origin_base)
                is_origin_ok = True
                if origin:
                    if _normalize(origin) != target:
                        is_origin_ok = False
                
                is_referer_ok = True
                if referer:
                    if not _normalize(referer).startswith(target):
                        is_referer_ok = False

                if not is_origin_ok or not is_referer_ok:
                    logger.warning(
                        "[security] 拦截到疑似跨站请求: path=%s, method=%s, origin=%s, referer=%s, expected_target=%s",
                        path, request.method, origin, referer, target
                    )
                    return JSONResponse({"detail": "非法来源请求"}, status_code=403)

        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # 兼容现有模板中大量 onclick 内联事件，避免交互失效。
        # 后续可改造成纯外链脚本事件绑定后再移除 'unsafe-inline'。
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if path.startswith("/api") or path.startswith("/login"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
    app.include_router(web_router)
    app.include_router(webhook_router)
    app.include_router(api_router)
    return app
