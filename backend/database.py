"""SQLite persistence (async SQLAlchemy 2.x) for bookmarked issues, with versioned migrations."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import AsyncIterator

from sqlalchemy import DateTime, String, inspect
from sqlalchemy.engine import Connection
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

# Bump this and add a step to _MIGRATIONS whenever a table changes. SQLite keeps the number in PRAGMA user_version.
SCHEMA_VERSION = 1
LEGACY_OWNER = "legacy"  # bookmarks saved before bookmarks belonged to a visitor; no cookie can ever match it


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for every Trailbit table."""


class Bookmark(Base):
    """An issue one visitor saved. ``id`` is the GitHub issue id; ``owner_id`` is the visitor's cookie id."""

    __tablename__ = "bookmarks"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(200), nullable=False)
    repo_owner: Mapped[str] = mapped_column(String(100), nullable=False)
    programming_language: Mapped[str] = mapped_column(String(60), nullable=False)
    github_issue_url: Mapped[str] = mapped_column(String(500), nullable=False)
    bookmarked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


def _migrate_1_bookmarks_belong_to_a_visitor(connection: Connection) -> None:
    """v0 -> v1: the shared bookmarks table gains owner_id. Old rows are kept under LEGACY_OWNER."""
    columns = {column["name"] for column in inspect(connection).get_columns("bookmarks")}
    if "owner_id" in columns:
        return
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_bookmarks_bookmarked_at")
    connection.exec_driver_sql("ALTER TABLE bookmarks RENAME TO bookmarks_v0")
    Base.metadata.create_all(connection)
    connection.exec_driver_sql(
        "INSERT INTO bookmarks (owner_id, id, title, repo_name, repo_owner, programming_language, github_issue_url, bookmarked_at) "
        f"SELECT '{LEGACY_OWNER}', id, title, repo_name, repo_owner, programming_language, github_issue_url, bookmarked_at FROM bookmarks_v0"
    )
    connection.exec_driver_sql("DROP TABLE bookmarks_v0")
    logger.info("Trailbit database: moved existing bookmarks to the per-visitor layout (kept under %r).", LEGACY_OWNER)


_MIGRATIONS = {1: _migrate_1_bookmarks_belong_to_a_visitor}


def _upgrade_schema(connection: Connection) -> None:
    """Bring any database, new or old, to SCHEMA_VERSION. Safe to run on every startup."""
    existing = set(inspect(connection).get_table_names())
    version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
    if "bookmarks" in existing:
        for step in range(version + 1, SCHEMA_VERSION + 1):
            _MIGRATIONS[step](connection)
    Base.metadata.create_all(connection)  # creates whatever is still missing (everything, on a fresh database)
    connection.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
    """Create the database folder, then create or migrate the tables. Safe to call on every startup."""
    _prepare_database_folder()
    if DATABASE_FILE is not None:
        logger.info("Trailbit database: %s", DATABASE_FILE)
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade_schema)


async def close_db() -> None:
    """Release the connection pool on shutdown."""
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one session per request."""
    async with async_session() as session:
        yield session
