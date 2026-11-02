"""Test setup. Everything is isolated: no real .env, no real GitHub or TinyFish, a throwaway SQLite file."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="trailbit-tests-"))

# Set before anything imports `backend`: it reads these (and .env) at import time. An empty value
# stops python-dotenv from filling in the developer's real key from .env.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["GITHUB_TOKEN"] = ""
os.environ["TINYFISH_API_KEY"] = ""
for name in ("RENDER", "PORT", "HOST", "DATA_DIR", "CORS_ORIGINS", "TRUST_PROXY", "ENABLE_DOCS", "SENTRY_DSN", "MAX_BOOKMARKS", "MAX_BODY_BYTES"):
    os.environ.pop(name, None)
# The app-level tests are not about limits, so keep them out of the way. test_security.py tests the limiter directly.
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_HEAVY_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_GLOBAL_PER_MINUTE"] = "1000000"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fakes import FakeGitHub  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services.engine import TinyFishEngine, get_engine  # noqa: E402
from backend.services.tinyfish_api import TinyFishClient  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake():
    return FakeGitHub()


def tinyfish_returning(markdown, *, status=200):
    """A TinyFish client with a key whose Fetch always answers with ``markdown``. ``calls`` counts the requests."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"results": [{"text": markdown}]})

    client = TinyFishClient(api_key="test-key", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client.calls = calls
    return client


@pytest.fixture
def make_engine(fake):
    def build(**kwargs):
        kwargs.setdefault("token", "")
        kwargs.setdefault("tinyfish", TinyFishClient(api_key=""))
        kwargs.setdefault("search_budget", 1000)
        return TinyFishEngine(client=fake.client(), **kwargs)

    return build


@pytest.fixture
async def api(make_engine):
    """A client for the whole app (middleware, routes, database) talking to the fake GitHub. Each test is a new visitor."""
    engine = make_engine()
    app.dependency_overrides[get_engine] = lambda: engine
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.engine = engine
            yield client
    app.dependency_overrides.clear()
