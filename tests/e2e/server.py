"""Starts Trailbit for the browser tests: the real frontend and API, with a fake GitHub, a stub TinyFish and a throwaway database.

Run by Playwright (see playwright.config.cjs). Test-only switches live under /__test/ and exist only in this process.
"""

import os
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
TMP = Path(tempfile.mkdtemp(prefix="trailbit-e2e-"))

os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{(TMP / 'e2e.db').as_posix()}",
    GITHUB_TOKEN="",
    TINYFISH_API_KEY="",
)
# Generous limits for the browser tests; tests/loadtest.py starts this server with tight ones to test the limiter itself.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("RATE_LIMIT_HEAVY_PER_MINUTE", "100000")
os.environ.setdefault("RATE_LIMIT_GLOBAL_PER_MINUTE", "1000000")
for name in ("RENDER", "DATA_DIR", "CORS_ORIGINS", "TRUST_PROXY", "ENABLE_DOCS", "SENTRY_DSN"):
    os.environ.pop(name, None)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fakes import FakeGitHub, build_data, iso, issue  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services.cache import TTLCache  # noqa: E402
from backend.services.engine import TinyFishEngine, get_engine  # noqa: E402
from backend.services.tinyfish_api import TinyFishClient  # noqa: E402

GUIDE = "# Contributing\n- Run the full test suite with pytest before you open a pull request.\n- Comment on the issue to claim it.\n"
fake = FakeGitHub()
fake.latency = 0.05
current = {"guide": GUIDE}
guide_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": [{"text": current["guide"]}]})))
engine = TinyFishEngine(token="", client=fake.client(), tinyfish=TinyFishClient(api_key="test-key", client=guide_client), search_budget=100000)
app.dependency_overrides[get_engine] = lambda: engine


HOSTILE_TITLE = '<img src=x onerror="window.__pwned=1"> Hostile title'


def install_hostile():
    """GitHub content written by someone trying to run script in other people's browsers."""
    def pull(url):
        return {"event": "cross-referenced", "source": {"issue": {"html_url": url, "state": "open", "pull_request": {"url": "x"}}}}

    item = issue(7001, 71, "acme", "pyparse", HOSTILE_TITLE, comments=2, updated=0.2, user="<b>evil</b>",
                 body="<script>window.__pwned=1</script> See [click me](javascript:window.__pwned=1) and src/evil/<b>x</b>.py and tests/test_ics.py",
                 labels=("good first issue", "<script>window.__pwned=1</script>", "bug"))
    fake.search["python"] = [item]
    fake.issues[("acme", "pyparse", 71)] = item
    fake.comments[("acme", "pyparse", 71)] = [
        {"user": {"login": '"><svg onload=window.__pwned=1>'}, "body": "I'd like to work on this <img src=x onerror=window.__pwned=1>", "created_at": iso(1)},
        {"user": {"login": "maint"}, "body": "ok", "created_at": iso(0.5)},
    ]
    fake.timelines[("acme", "pyparse", 71)] = [pull("javascript:window.__pwned=1"), pull("https://github.com/acme/pyparse/pull/9")]
    current["guide"] = "- Run the tests <img src=x onerror=window.__pwned=1> before you commit to the branch.\n- Comment on the issue to claim it.\n"


def paged_python(first, count):
    return [issue(first + i, 50 + first - 5000 + i, "acme", "pyparse", f"Paged issue {first + i}", updated=1 + i) for i in range(count)]


@app.middleware("http")
async def test_switches(request: Request, call_next):
    path, params = request.url.path, request.query_params
    if path == "/__test/reset":  # between tests: forget cached GitHub answers and turn every switch off
        engine._search_cache = TTLCache(300.0)
        engine._issue_cache = TTLCache(600.0)
        engine._guide_cache = TTLCache(3600.0)
        fake.down = fake.search_rate_limited = False
        fake.pages = {}
        fake.search, fake.issues, fake.repos, fake.profiles, fake.comments, fake.timelines = build_data()
        current["guide"] = GUIDE
        return JSONResponse({"ok": True})
    if path == "/__test/set":
        if "down" in params:
            fake.down = params["down"] == "1"
        if "rate_limited" in params:
            fake.search_rate_limited = params["rate_limited"] == "1"
        if params.get("hostile") == "1":
            install_hostile()
        if "paged" in params:  # a full first page (6 = the per-language page size) and a short second one
            fake.pages = {("python", 1): paged_python(5001, 6), ("python", 2): paged_python(5007, 2)} if params["paged"] == "1" else {}
        return JSONResponse({"ok": True})
    return await call_next(request)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8790")), log_level="warning")
