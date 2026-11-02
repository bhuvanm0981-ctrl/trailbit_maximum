"""Configuration rules, the cache and request budget, and the database migration."""

import asyncio
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend import config, database
from backend.services.cache import SlidingBudget, TTLCache

CONFIG_VARS = ("PORT", "HOST", "RENDER", "DATA_DIR", "DATABASE_URL", "TRUST_PROXY", "ENABLE_DOCS", "CORS_ORIGINS",
               "RATE_LIMIT_PER_MINUTE", "RATE_LIMIT_HEAVY_PER_MINUTE", "RATE_LIMIT_GLOBAL_PER_MINUTE", "MAX_BODY_BYTES", "MAX_BOOKMARKS")


@pytest.fixture
def env(monkeypatch):
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ------------------------------------------------------------------ config
def test_port_and_host(env):
    assert config.get_port() == 10000 and config.get_host() == "127.0.0.1"
    env.setenv("PORT", " 8080 ")
    assert config.get_port() == 8080
    env.setenv("RENDER", "True")
    assert config.get_host() == "0.0.0.0"  # noqa: S104
    env.setenv("HOST", "127.0.0.1")
    assert config.get_host() == "127.0.0.1"  # an explicit HOST wins


@pytest.mark.parametrize("value", ["abc", "80.5", "0", "70000", "-1"])
def test_bad_port_is_a_clear_error(env, value):
    env.setenv("PORT", value)
    with pytest.raises(config.ConfigError, match="PORT must be"):
        config.get_port()


def test_proxy_docs_and_cors_defaults(env):
    assert (config.trust_proxy(), config.docs_enabled(), config.get_cors_origins()) == (False, True, [])
    env.setenv("RENDER", "true")
    assert (config.trust_proxy(), config.docs_enabled()) == (True, False)  # production: trust Render's proxy, hide the docs
    env.setenv("ENABLE_DOCS", "yes")
    env.setenv("TRUST_PROXY", "off")
    assert (config.trust_proxy(), config.docs_enabled()) == (False, True)
    env.setenv("CORS_ORIGINS", "https://a.example/, http://localhost:3000")
    assert config.get_cors_origins() == ["https://a.example", "http://localhost:3000"]
    env.setenv("CORS_ORIGINS", "a.example")
    with pytest.raises(config.ConfigError):
        config.get_cors_origins()


def test_limits(env):
    assert config.get_rate_limits() == (120, 30, 900) and config.get_max_body_bytes() == 16384 and config.get_max_bookmarks() == 200
    env.setenv("RATE_LIMIT_HEAVY_PER_MINUTE", "5")
    env.setenv("MAX_BOOKMARKS", "3")
    assert config.get_rate_limits()[1] == 5 and config.get_max_bookmarks() == 3
    env.setenv("MAX_BODY_BYTES", "10")
    with pytest.raises(config.ConfigError):
        config.get_max_body_bytes()


def test_database_location(env, tmp_path):
    assert Path(config.get_database_url().database) == config.ROOT_DIR / "trailbit.db"
    env.setenv("DATA_DIR", str(tmp_path / "vol" / "nested"))
    assert Path(config.get_database_url().database) == (tmp_path / "vol" / "nested" / "trailbit.db").resolve()
    env.setenv("DATA_DIR", "var/data")
    assert Path(config.get_database_url().database) == (config.ROOT_DIR / "var" / "data" / "trailbit.db").resolve()
    env.setenv("DATABASE_URL", "sqlite:///./local.db")
    url = config.get_database_url()
    assert url.drivername == "sqlite+aiosqlite" and Path(url.database) == (config.ROOT_DIR / "local.db").resolve()
    env.setenv("DATABASE_URL", "sqlite+aiosqlite:////var/data/x.db")
    assert config.get_database_url().database == "/var/data/x.db"
    env.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    assert config.sqlite_file(config.get_database_url()) is None


@pytest.mark.parametrize("url", ["postgresql://u:secret@h/db", "postgres://u:secret@h/db", "mysql+aiomysql://u:secret@h/d"])
def test_non_sqlite_database_url_is_refused_without_leaking_the_password(env, url):
    env.setenv("DATABASE_URL", url)
    with pytest.raises(config.ConfigError, match="must be a SQLite URL") as error:
        config.get_database_url()
    assert "secret" not in str(error.value) and "DATA_DIR" in str(error.value)


# ------------------------------------------------------------------ cache
pytestmark = []
anyio = pytest.mark.anyio


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@anyio
async def test_cache_hits_and_expiry():
    clock, calls = Clock(), []

    async def make():
        calls.append(1)
        return len(calls)

    cache = TTLCache(10, clock=clock)
    assert [await cache.get_or_create("k", make) for _ in range(3)] == [1, 1, 1]
    clock.now += 11
    assert await cache.get_or_create("k", make) == 2


@anyio
async def test_cache_shares_inflight_calls_and_never_caches_failures():
    calls = []

    async def slow():
        calls.append(1)
        await asyncio.sleep(0.05)
        return "value"

    cache = TTLCache(10)
    assert await asyncio.gather(*(cache.get_or_create("k", slow) for _ in range(5))) == ["value"] * 5
    assert len(calls) == 1

    attempts = []

    async def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("down")
        return "ok"

    cache = TTLCache(10)
    with pytest.raises(RuntimeError):
        await cache.get_or_create("k", flaky)
    assert await cache.get_or_create("k", flaky) == "ok"  # the failure was not remembered


@anyio
async def test_cache_serves_stale_when_the_refresh_fails():
    clock, state = Clock(), {"fail": False}

    async def make():
        if state["fail"]:
            raise RuntimeError("GitHub is down")
        return "fresh"

    cache = TTLCache(10, stale_ttl=100, clock=clock)
    assert await cache.get_or_create("k", make) == "fresh"
    state["fail"] = True
    clock.now += 50  # expired, but inside the stale window
    assert await cache.get_or_create("k", make) == "fresh"
    clock.now += 100  # past the stale window: the error is real again
    with pytest.raises(RuntimeError):
        await cache.get_or_create("k", make)


@anyio
async def test_cache_without_a_stale_window_raises():
    clock, state = Clock(), {"fail": False}

    async def make():
        if state["fail"]:
            raise RuntimeError("down")
        return 1

    cache = TTLCache(10, clock=clock)
    await cache.get_or_create("k", make)
    state["fail"] = True
    clock.now += 11
    with pytest.raises(RuntimeError):
        await cache.get_or_create("k", make)


@anyio
async def test_cache_is_bounded():
    cache = TTLCache(1000, max_items=3)

    async def make():
        return 1

    for key in range(10):
        await cache.get_or_create(key, make)
    assert len(cache) <= 3


def test_budget_allows_a_limit_then_reports_the_wait():
    clock = Clock()
    budget = SlidingBudget(2, window=60, clock=clock)
    assert budget.try_acquire() == 0 and budget.try_acquire() == 0
    wait = budget.try_acquire()
    assert 1 <= wait <= 60
    clock.now += 61
    assert budget.try_acquire() == 0


# ------------------------------------------------------------------ database migration
OLD_SCHEMA = """CREATE TABLE bookmarks (id VARCHAR(40) PRIMARY KEY, title VARCHAR(500) NOT NULL, repo_name VARCHAR(200) NOT NULL,
    repo_owner VARCHAR(100) NOT NULL, programming_language VARCHAR(60) NOT NULL, github_issue_url VARCHAR(500) NOT NULL,
    bookmarked_at DATETIME NOT NULL);
    CREATE INDEX ix_bookmarks_bookmarked_at ON bookmarks (bookmarked_at);"""


async def upgrade(path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(database._upgrade_schema)
    return engine


@anyio
async def test_old_shared_bookmarks_are_kept_under_the_legacy_owner(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as raw:
        raw.executescript(OLD_SCHEMA)
        raw.execute("INSERT INTO bookmarks VALUES ('1','Old title','r','o','Go','https://github.com/o/r/issues/1','2026-01-01 00:00:00')")
    engine = await upgrade(path)
    async with engine.connect() as connection:
        rows = (await connection.execute(text("SELECT owner_id, id, title FROM bookmarks"))).all()
        version = (await connection.execute(text("PRAGMA user_version"))).scalar_one()
        leftovers = (await connection.execute(text("SELECT name FROM sqlite_master WHERE name = 'bookmarks_v0'"))).all()
    await engine.dispose()
    assert rows == [(database.LEGACY_OWNER, "1", "Old title")] and version == database.SCHEMA_VERSION and not leftovers


@anyio
async def test_migration_is_idempotent_and_a_fresh_database_gets_the_current_schema(tmp_path):
    path = tmp_path / "fresh.db"
    for _ in range(2):  # the second run must change nothing and not fail
        engine = await upgrade(path)
        async with engine.connect() as connection:
            columns = {row[1] for row in (await connection.execute(text("PRAGMA table_info(bookmarks)"))).all()}
            version = (await connection.execute(text("PRAGMA user_version"))).scalar_one()
        await engine.dispose()
        assert "owner_id" in columns and version == database.SCHEMA_VERSION


def test_legacy_owner_can_never_be_a_real_visitor_cookie():
    from backend.visitor import _VALID

    assert not _VALID.match(database.LEGACY_OWNER)
