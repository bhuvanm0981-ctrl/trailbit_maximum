"""Operational endpoints: /health says the process is up, /ready says it can do its job."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..database import async_session
from ..services.engine import TinyFishEngine, get_engine

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health() -> dict:
    """Cheap liveness check for the platform's health probe. Does not touch the database or GitHub."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(engine: TinyFishEngine = Depends(get_engine)):
    """Checks the database and reports the GitHub quota last seen. 503 if the database is unreachable."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # any failure here means bookmarks cannot work
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "error"})
    return {
        "status": "ok",
        "database": "ok",
        "github": {"authenticated": engine.authenticated, "quota": engine.quota()},
        "tinyfish": {"enabled": engine.tinyfish_enabled},
    }
