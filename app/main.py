"""FastAPI application factory and entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import (
    approvals,
    conversations,
    dashboard,
    demo,
    diagnosis,
    health,
    projects,
    workflows,
)
from app.api.routes import (
    settings as settings_routes,
)
from app.core.config import ConfigError, Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, redact_text, register_secret
from app.core.security import SESSION_COOKIE, verify_session_token
from app.services.container import AppContainer

APP_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def _register_secrets(settings: Settings) -> None:
    for value in (
        settings.liara_token,
        settings.auth_token,
        settings.app_secret_key.get_secret_value(),
        settings.llm_api_key.get_secret_value(),
    ):
        register_secret(value)


def create_app(
    settings: Settings | None = None,
    *,
    container: AppContainer | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    _register_secrets(settings)
    app_container = container or AppContainer(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app_container.start()
        app.state.container = app_container
        logger.info("LiaraPilot started", extra={"event_data": {
            "mode": "demo" if settings.demo_mode else "live",
            "port": settings.app_port,
        }})
        try:
            yield
        finally:
            await app_container.stop()

    app = FastAPI(
        title="LiaraPilot AI Engineer",
        description=(
            "AI infrastructure engineer for Liara-hosted applications: evidence-based "
            "diagnosis, human-in-the-loop repair, deployment and verification."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.container = app_container

    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    templates.env.filters["mask"] = lambda value: redact_text(str(value or ""))[:400]
    templates.env.filters["short_id"] = lambda value: (str(value or "")[-12:])
    app.state.templates = templates

    static_dir = APP_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ------------------------------------------------------------------
    # auth middleware (only when APP_AUTH_ENABLED=true)
    # ------------------------------------------------------------------
    public_prefixes = ("/static", "/login", "/favicon.ico", "/docs", "/redoc",
                       "/openapi.json", "/api/health")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not settings.app_auth_enabled:
            return await call_next(request)
        path = request.url.path
        if any(path == p or path.startswith(p + "/") or path.startswith(p)
               for p in public_prefixes):
            return await call_next(request)
        token = request.headers.get("x-app-token") or ""
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
        cookie = request.cookies.get(SESSION_COOKIE)
        import hmac

        authorised = bool(
            (token and hmac.compare_digest(token, settings.auth_token))
            or verify_session_token(settings.app_secret_key.get_secret_value(), cookie)
        )
        if authorised:
            return await call_next(request)
        if path.startswith("/api"):
            return JSONResponse(
                {"error": {"code": "auth_required",
                           "message": "Authentication required (X-App-Token or session cookie)."}},
                status_code=401,
            )
        return RedirectResponse(f"/login?next={quote(path)}", status_code=303)

    # ------------------------------------------------------------------
    # error handling
    # ------------------------------------------------------------------
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> Response:
        wants_html = (
            not request.url.path.startswith("/api")
            and "text/html" in request.headers.get("accept", "")
        )
        if wants_html:
            return templates.TemplateResponse(
                request, "error.html",
                {
                    "request": request, "page": "error", "app_name": settings.app_name,
                    "demo_mode": settings.demo_mode, "simulated": app_container.adapter.simulated,
                    "auth_enabled": settings.app_auth_enabled,
                    "error": {"code": exc.code, "message": redact_text(exc.message)},
                },
                status_code=exc.http_status,
            )
        return JSONResponse(exc.to_dict(), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic puts the original exception instance in ``ctx`` for custom
        # validators; it is not JSON serialisable, so ctx values are stringified.
        errors = []
        for err in exc.errors()[:5]:
            clean = {key: value for key, value in err.items() if key != "ctx"}
            if err.get("ctx"):
                clean["ctx"] = {str(k): str(v) for k, v in err["ctx"].items()}
            errors.append(clean)
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Invalid request payload.",
                       "details": {"errors": errors}}},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"event_data": {"path": request.url.path}})
        return JSONResponse(
            {"error": {"code": "internal_error",
                       "message": "Internal server error. See server logs for details."}},
            status_code=500,
        )

    # ------------------------------------------------------------------
    # routers
    # ------------------------------------------------------------------
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(diagnosis.router)
    app.include_router(workflows.router)
    app.include_router(approvals.router)
    app.include_router(settings_routes.router)
    app.include_router(demo.router)
    app.include_router(conversations.router)
    app.include_router(dashboard.router)

    # ------------------------------------------------------------------
    # conversational frontend (React build served by FastAPI)
    # ------------------------------------------------------------------
    chat_dir = static_dir / "chat"

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def chat_shell() -> Response:
        index = chat_dir / "index.html"
        if index.is_file():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse(
            "<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>"
            "<title>LiaraPilot</title>"
            "<body style='font-family:sans-serif;padding:2rem;line-height:2'>"
            "<h1>LiaraPilot</h1><p>فرانت‌اند ساخته نشده است. در پوشه web دستورهای "
            "<code>npm install</code> و <code>npm run build</code> را اجرا کنید.</p>"
            "<p><a href='/dashboard'>پنل قدیمی</a></p></body></html>",
            status_code=200,
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    return app


def _load_app() -> FastAPI:
    try:
        return create_app()
    except ConfigError as exc:  # pragma: no cover - startup path
        print(f"[LiaraPilot] configuration error:\n{exc}", flush=True)  # noqa: T201
        raise


app = _load_app()


def run() -> None:  # pragma: no cover - console entry point
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app", host=settings.app_host, port=settings.app_port,
        log_level=settings.log_level.lower(), reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
