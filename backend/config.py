"""Deployment settings, read from environment variables (and from .env when developing locally).

Environment variables
---------------------
PORT          Port to listen on. Defaults to 10000, Render's default for web services.
HOST          Interface to bind. Defaults to 0.0.0.0 on Render (it sets RENDER=true) and to
              127.0.0.1 everywhere else, so a laptop is not exposed to the network by accident.
DATA_DIR      Folder that holds trailbit.db. Point it at a persistent disk, for example /var/data.
              Created if missing. A relative value is resolved against the repository root.
DATABASE_URL  Full SQLite URL, used instead of DATA_DIR when you need a different file name.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DEFAULT_PORT = 10000
DATABASE_FILENAME = "trailbit.db"


class ConfigError(RuntimeError):
    """An environment variable is set to something Trailbit cannot use."""


def get_port() -> int:
    raw = os.getenv("PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError(f"PORT must be a whole number, but it is {raw!r}.") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"PORT must be between 1 and 65535, but it is {port}.")
    return port


def get_host() -> str:
    host = os.getenv("HOST", "").strip()
    if host:
        return host
    # Render must reach the service from outside the container, so it needs 0.0.0.0.
    return "0.0.0.0" if os.getenv("RENDER", "").strip().lower() == "true" else "127.0.0.1"


def get_data_dir() -> Path:
    """Absolute folder for the database file: DATA_DIR if set, otherwise the repository root."""
    raw = os.getenv("DATA_DIR", "").strip()
    if not raw:
        return ROOT_DIR
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else ROOT_DIR / path).resolve()


def get_database_url() -> URL:
    """The async SQLite URL, always pointing at an absolute file path."""
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        return URL.create("sqlite+aiosqlite", database=str(get_data_dir() / DATABASE_FILENAME))

    try:
        url = make_url(raw)
    except Exception as exc:  # sqlalchemy raises ArgumentError for malformed URLs
        raise ConfigError(f"DATABASE_URL is not a valid database URL: {exc}") from None
    if not url.drivername.startswith("sqlite"):
        raise ConfigError(
            "DATABASE_URL must be a SQLite URL such as sqlite+aiosqlite:////var/data/trailbit.db, "
            f"but it starts with {url.drivername!r}. Trailbit stores bookmarks in SQLite. "
            "If Render added a Postgres DATABASE_URL, rename or remove it and use DATA_DIR instead."
        )
    if url.drivername == "sqlite":
        url = url.set(drivername="sqlite+aiosqlite")  # the async driver is required
    database = url.database
    already_placed = database.startswith(("/", "file:")) or Path(database).is_absolute() if database else True
    if database and database != ":memory:" and not already_placed:
        url = url.set(database=str((ROOT_DIR / database).resolve()))  # never relative to the launch directory
    return url


def sqlite_file(url: URL) -> Optional[Path]:
    """The database file behind a SQLite URL, or None for an in-memory database."""
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database)
