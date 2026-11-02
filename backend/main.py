"""Trailbit API entrypoint.

Local development, from the repository root:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

Production (Render sets PORT; HOST defaults to 0.0.0.0 there), either of:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
    python -m backend.main        # reads HOST and PORT from the environment, PORT defaults to 10000
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from .config import (
    docs_enabled,
    get_cors_origins,
    get_host,
    get_max_body_bytes,
    get_port,
    get_rate_limits,
    get_sentry_dsn,
    is_render,
    trust_proxy,
)
from .database import close_db, init_db
from .routes import bookmarks, contribution_plan, discover, meta, verify
from .security import BodyLimitMiddleware, RateLimitMiddleware, RequestContextMiddleware
from .services.engine import engine
from .services.github import UpstreamError

logger = logging.getLogger("uvicorn.error")


def _init_error_tracking() -> None:
    """Report unhandled errors to Sentry when SENTRY_DSN is set. Optional: the app runs fine without it."""
    dsn = get_sentry_dsn()
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, send_default_pii=False, traces_sample_rate=0.0, environment="render" if is_render() else "local")
        logger.info("Trailbit: error tracking is on (Sentry).")
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed. Run: pip install sentry-sdk")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_error_tracking()
    await init_db()  # create or migrate the SQLite tables
    if not engine.authenticated:
        logger.warning("GITHUB_TOKEN is not set: GitHub allows only 10 searches a minute and 60 other requests an hour.")
    yield
    await engine.aclose()
    await close_db()


docs = docs_enabled()
app = FastAPI(
    title="Trailbit",
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/docs" if docs else None,
    redoc_url="/redoc" if docs else None,
    openapi_url="/openapi.json" if docs else None,
)

# Middleware runs from the last one added (outermost) to the first (closest to the routes).
per_visitor, heavy_per_visitor, overall = get_rate_limits()
app.add_middleware(BodyLimitMiddleware, max_bytes=get_max_body_bytes())
app.add_middleware(
    RateLimitMiddleware, per_visitor=per_visitor, heavy_per_visitor=heavy_per_visitor, overall=overall, trust_proxy=trust_proxy()
)
app.add_middleware(GZipMiddleware, minimum_size=500)
cors_origins = get_cors_origins()
if cors_origins:  # the bundled frontend is same-origin and needs no CORS; this is only for a frontend hosted elsewhere
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"], allow_credentials=True)
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(UpstreamError)
async def upstream_error_handler(_: Request, exc: UpstreamError) -> JSONResponse:
    """GitHub is down, slow or rate limiting us: tell the client plainly instead of a 500."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)}, headers=exc.headers)


@app.exception_handler(RecursionError)
async def too_nested_handler(_: Request, exc: RecursionError) -> JSONResponse:
    """A JSON body nested thousands of levels deep overflows the parser; that is a bad request, not a server fault."""
    return JSONResponse(status_code=422, content={"detail": "That request body is nested too deeply to read."})


app.include_router(meta.router)
for router in (discover.router, verify.router, contribution_plan.router, bookmarks.router):
    app.include_router(router, prefix="/api")


# Serve the frontend from the same origin (registered last so /api, /health and /ready win).
_frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


def run() -> None:
    """Start uvicorn on HOST and PORT from the environment (PORT defaults to 10000)."""
    import uvicorn

    uvicorn.run(app, host=get_host(), port=get_port())


if __name__ == "__main__":
    run()
