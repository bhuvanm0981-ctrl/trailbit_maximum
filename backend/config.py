"""Deployment settings, read from environment variables (and from .env when developing locally).

Environment variables (all optional)
------------------------------------
PORT                       Port to listen on. Defaults to 10000, Render's default for web services.
HOST                       Interface to bind. Defaults to 0.0.0.0 on Render (it sets RENDER=true) and to
                           127.0.0.1 everywhere else, so a laptop is not exposed to the network by accident.
DATA_DIR                   Folder that holds trailbit.db. Point it at a persistent disk, for example /var/data.
                           Created if missing. A relative value is resolved against the repository root.
DATABASE_URL               Full SQLite URL, used instead of DATA_DIR when you need a different file name.
GITHUB_TOKEN               Raises GitHub's rate limits (no scopes needed).
TINYFISH_API_KEY           Lets plans quote each repository's CONTRIBUTING guide.
CORS_ORIGINS               Comma-separated origins allowed to call the API from a browser. Unset means
                           same-origin only, which is what the bundled frontend needs.
RATE_LIMIT_PER_MINUTE      Requests per visitor per minute to /api (default 120).
RATE_LIMIT_HEAVY_PER_MINUTE  Per visitor per minute for routes that call GitHub (default 30).
RATE_LIMIT_GLOBAL_PER_MINUTE Across all visitors (default 900).
TRUST_PROXY                true/false. Read the visitor's IP from X-Forwarded-For. Defaults to true on Render.
MAX_BODY_BYTES             Largest request body accepted (default 16384).
MAX_BOOKMARKS              Bookmarks one visitor may keep (default 200).
ENABLE_DOCS                true/false. Serve /docs and /openapi.json. Defaults to false on Render.
SENTRY_DSN                 Report unhandled errors to Sentry (needs `pip install sentry-sdk`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DEFAULT_PORT = 10000
DATABASE_FILENAME = "trailbit.db"


class ConfigError(RuntimeError):
    """An environment variable is set to something Trailbit cannot use."""


def _flag(name: str) -> Optional[bool]:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, but it is {raw!r}.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, but it is {value}.")
    return value


def is_render() -> bool:
    return os.getenv("RENDER", "").strip().lower() == "true"


# --------------------------------------------------------------------------- server
def get_port() -> int:
    return _int_env("PORT", DEFAULT_PORT, 1, 65535)


def get_host() -> str:
    host = os.getenv("HOST", "").strip()
    if host:
        return host
    # Render must reach the service from outside the container, so it needs 0.0.0.0.
    return "0.0.0.0" if is_render() else "127.0.0.1"


def trust_proxy() -> bool:
    flag = _flag("TRUST_PROXY")
    return is_render() if flag is None else flag


def docs_enabled() -> bool:
    flag = _flag("ENABLE_DOCS")
    return (not is_render()) if flag is None else flag


def get_cors_origins() -> List[str]:
    origins = [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    for origin in origins:
        if origin != "*" and not origin.startswith(("http://", "https://")):
            raise ConfigError(f"CORS_ORIGINS entries must start with http:// or https://, but one is {origin!r}.")
    return origins


def get_rate_limits() -> tuple[int, int, int]:
    """(per visitor, per visitor for GitHub-backed routes, across everyone), each per minute."""
    return (
        _int_env("RATE_LIMIT_PER_MINUTE", 120, 1, 100_000),
        _int_env("RATE_LIMIT_HEAVY_PER_MINUTE", 30, 1, 100_000),
        _int_env("RATE_LIMIT_GLOBAL_PER_MINUTE", 900, 1, 1_000_000),
    )


def get_max_body_bytes() -> int:
    return _int_env("MAX_BODY_BYTES", 16_384, 256, 10_000_000)


def get_max_bookmarks() -> int:
    return _int_env("MAX_BOOKMARKS", 200, 1, 10_000)


def get_sentry_dsn() -> str:
    return os.getenv("SENTRY_DSN", "").strip()


# --------------------------------------------------------------------------- database
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
