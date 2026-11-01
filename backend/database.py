"""SQLite persistence (async SQLAlchemy 2.x) for bookmarked issues."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import DateTime, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import ConfigError, get_database_url, sqlite_file

# Reuse uvicorn's handler so these lines appear in the Render log without extra logging setup.
logger = logging.getLogger("uvicorn.error")

# An absolute path, resolved once at import. By default <repo>/trailbit.db; set DATA_DIR to put it
# on a persistent disk (see config.py), or DATABASE_URL to choose the file name too.
DATABASE_URL = get_database_url()
DATABASE_FILE = sqlite_file(DATABASE_URL)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for every Trailbit table."""


class Bookmark(Base):
    """An issue the user saved. ``id`` is the GitHub issue id, so one issue is stored once."""

    __tablename__ = "bookmarks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(200), nullable=False)
    repo_owner: Mapped[str] = mapped_column(String(100), nullable=False)
    programming_language: Mapped[str] = mapped_column(String(60), nullable=False)
    github_issue_url: Mapped[str] = mapped_column(String(500), nullable=False)
    bookmarked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


def _prepare_database_folder() -> None:
    """Create the folder that will hold the SQLite file and make sure it can be written to."""
    if DATABASE_FILE is None:
        return
    folder = DATABASE_FILE.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"Cannot create the database folder {folder}: {exc}.") from exc
    if not os.access(folder, os.W_OK):
        raise ConfigError(
            f"The database folder {folder} is not writable. On Render, attach a disk, mount it at "
            "that path (or at the path you set in DATA_DIR) and redeploy."
        )


async def init_db() -> None:
    """Create the database folder and any missing tables. Safe to call on every startup."""
    _prepare_database_folder()
    if DATABASE_FILE is not None:
        logger.info("Trailbit database: %s", DATABASE_FILE)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Release the connection pool on shutdown."""
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one session per request."""
    async with async_session() as session:
        yield session
