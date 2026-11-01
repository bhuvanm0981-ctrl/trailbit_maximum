"""Trailbit API entrypoint.

Local development, from the repository root:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

Production (Render sets PORT; HOST defaults to 0.0.0.0 there), either of:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
    python -m backend.main        # reads HOST and PORT from the environment, PORT defaults to 10000
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_host, get_port
from .database import close_db, init_db
from .routes import bookmarks, contribution_plan, discover, verify
from .services.tinyfish import UpstreamError, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()  # create the SQLite tables on first run
    yield
    await engine.aclose()
    await close_db()


app = FastAPI(title="Trailbit", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(UpstreamError)
async def upstream_error_handler(_: Request, exc: UpstreamError) -> JSONResponse:
    """GitHub is down, slow or rate limiting us: tell the client plainly instead of a 500."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)}, headers=exc.headers)


app.include_router(discover.router, prefix="/api")
app.include_router(verify.router, prefix="/api")
app.include_router(contribution_plan.router, prefix="/api")
app.include_router(bookmarks.router, prefix="/api")


@app.get("/health", tags=["meta"])
async def health_check() -> dict:
    return {"status": "ok"}


# Serve the frontend from the same origin (registered last so /api and /health win).
_frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


def run() -> None:
    """Start uvicorn on HOST and PORT from the environment (PORT defaults to 10000)."""
    import uvicorn

    uvicorn.run(app, host=get_host(), port=get_port())


if __name__ == "__main__":
    run()
