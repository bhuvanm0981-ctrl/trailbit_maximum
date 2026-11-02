"""The middleware on their own, against a tiny app, so each rule is tested without the rest of Trailbit."""

import httpx
import pytest

from backend.security import BodyLimitMiddleware, RateLimitMiddleware, RequestContextMiddleware

pytestmark = pytest.mark.anyio


async def echo_app(scope, receive, send):
    """Reads the whole body, then answers 200."""
    if scope["type"] != "http":
        return
    while True:
        message = await receive()
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})


def client_for(app, ip="203.0.113.5"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="http://test")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def limiter(clock=None, **overrides):
    options = {"per_visitor": 3, "heavy_per_visitor": 2, "overall": 100, "trust_proxy": False, "clock": clock or Clock()}
    options.update(overrides)
    return RateLimitMiddleware(echo_app, **options)


# ------------------------------------------------------------------ rate limit
async def test_a_visitor_gets_a_window_then_a_429_with_retry_after():
    clock = Clock()
    async with client_for(limiter(clock)) as client:
        assert [(await client.get("/api/facets")).status_code for _ in range(3)] == [200, 200, 200]
        blocked = await client.get("/api/facets")
        assert blocked.status_code == 429 and blocked.json()["detail"].startswith("Too many requests")
        assert 1 <= int(blocked.headers["retry-after"]) <= 60
        clock.now += 61
        assert (await client.get("/api/facets")).status_code == 200  # the window slid past the old requests


async def test_github_backed_routes_have_a_smaller_allowance_and_a_separate_one():
    async with client_for(limiter()) as client:
        assert [(await client.get("/api/issues")).status_code for _ in range(3)] == [200, 200, 429]
        assert (await client.post("/api/verify", content=b"{}")).status_code == 429  # every GitHub-backed route spends the same allowance
        assert [(await client.get("/api/facets")).status_code for _ in range(3)] == [200, 200, 200]  # ordinary traffic is counted apart
        assert (await client.get("/api/bookmarks")).status_code == 429  # ...and has its own, larger allowance (3 here), now used up


async def test_visitors_are_limited_separately_but_everyone_shares_the_global_cap():
    app = limiter(per_visitor=2, overall=3)
    async with client_for(app, "198.51.100.1") as a, client_for(app, "198.51.100.2") as b:
        assert (await a.get("/api/x")).status_code == 200 and (await a.get("/api/x")).status_code == 200
        assert (await a.get("/api/x")).status_code == 429  # A used their two
        assert (await b.get("/api/x")).status_code == 200  # B is unaffected...
        assert (await b.get("/api/x")).status_code == 429  # ...until the global cap of three is reached


async def test_only_api_paths_are_limited_and_preflights_are_free():
    async with client_for(limiter(per_visitor=1)) as client:
        for _ in range(5):
            assert (await client.get("/")).status_code == 200 and (await client.get("/health")).status_code == 200
        assert (await client.get("/api/x")).status_code == 200
        assert (await client.request("OPTIONS", "/api/x")).status_code == 200


async def test_proxy_header_is_only_trusted_when_asked():
    spoof = {"X-Forwarded-For": "192.0.2.77, 10.0.0.1"}
    async with client_for(limiter(per_visitor=1)) as client:  # not trusted: every request is the socket's peer
        assert (await client.get("/api/x", headers=spoof)).status_code == 200
        assert (await client.get("/api/x", headers={"X-Forwarded-For": "192.0.2.99"})).status_code == 429
    async with client_for(limiter(per_visitor=1, trust_proxy=True)) as client:  # trusted: the first address is the visitor
        assert (await client.get("/api/x", headers=spoof)).status_code == 200
        assert (await client.get("/api/x", headers={"X-Forwarded-For": "192.0.2.99"})).status_code == 200
        assert (await client.get("/api/x", headers=spoof)).status_code == 429
        assert (await client.get("/api/x", headers={"X-Forwarded-For": "not-an-ip"})).status_code == 200  # falls back to the peer


# ------------------------------------------------------------------ body limit
async def test_body_over_the_limit_is_refused_by_declared_length_and_by_streaming():
    async with client_for(BodyLimitMiddleware(echo_app, max_bytes=100)) as client:
        assert (await client.post("/x", content=b"a" * 100)).status_code == 200
        declared = await client.post("/x", content=b"a" * 101)
        assert declared.status_code == 413 and "too large" in declared.json()["detail"]

        async def chunks():
            for _ in range(5):
                yield b"a" * 30  # no Content-Length: only the running total can reveal it is too big

        assert (await client.post("/x", content=chunks())).status_code == 413
        assert (await client.get("/x")).status_code == 200  # reads have no body to limit


# ------------------------------------------------------------------ request context
async def test_every_response_gets_a_request_id_security_headers_and_a_cache_policy():
    async with client_for(RequestContextMiddleware(echo_app)) as client:
        page = await client.get("/")
        assert len(page.headers["x-request-id"]) == 12
        assert page.headers["x-content-type-options"] == "nosniff" and page.headers["x-frame-options"] == "DENY"
        assert page.headers["referrer-policy"] and page.headers["permissions-policy"]
        assert "script-src 'self'" in page.headers["content-security-policy"] and "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-cache" and "strict-transport-security" not in page.headers
        assert (await client.get("/api/issues")).headers["cache-control"] == "no-store"
        assert (await client.get("/api/facets")).headers["cache-control"] == "public, max-age=300"
        assert "max-age=2592000" in (await client.get("/fonts/a.woff2")).headers["cache-control"]
        assert "max-age=604800" in (await client.get("/img/a.png")).headers["cache-control"]
        assert "content-security-policy" not in (await client.get("/docs")).headers  # the docs UI loads its assets from a CDN


async def test_request_id_is_echoed_only_when_it_is_safe_and_hsts_follows_https():
    async with client_for(RequestContextMiddleware(echo_app)) as client:
        assert (await client.get("/", headers={"X-Request-ID": "trace-123456"})).headers["x-request-id"] == "trace-123456"
        assert (await client.get("/", headers={"X-Request-ID": "x"})).headers["x-request-id"] != "x"  # too short to be one
        assert (await client.get("/", headers={"X-Request-ID": "a b\"<script>"})).headers["x-request-id"] != "a b\"<script>"
        assert "includeSubDomains" in (await client.get("/", headers={"X-Forwarded-Proto": "https"})).headers["strict-transport-security"]
