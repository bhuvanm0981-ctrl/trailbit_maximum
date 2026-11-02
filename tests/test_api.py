"""The whole app: routes, bookmarks per visitor, security headers, errors. GitHub is the fake one."""

import json

import httpx
import pytest

from backend.main import app
from backend.services.engine import get_engine

pytestmark = pytest.mark.anyio
ISSUE = "https://github.com/acme/pyparse/issues/11"


def body(url=ISSUE):
    return {"github_url": url}


# ------------------------------------------------------------------ meta
async def test_health_ready_and_unknown_routes(api):
    assert (await api.get("/health")).json() == {"status": "ok"}
    ready = (await api.get("/ready")).json()
    assert ready["status"] == "ok" and ready["database"] == "ok" and ready["github"]["authenticated"] is False and ready["tinyfish"] == {"enabled": False}
    missing = await api.get("/api/nope")
    assert missing.status_code == 404 and missing.json() == {"detail": "Not Found"}
    assert (await api.post("/")).status_code == 405


async def test_ready_quota_appears_after_github_has_been_called(api):
    await api.post("/api/verify", json=body())
    assert (await api.get("/ready")).json()["github"]["quota"]["core"]["limit"] == 60


async def test_the_frontend_is_served_and_unhandled_errors_are_json_with_a_request_id(api):
    page = await api.get("/")
    assert page.status_code == 200 and "Trailbit" in page.text

    class Broken:
        async def research_issue(self, url):
            raise RuntimeError("boom")

    app.dependency_overrides[get_engine] = lambda: Broken()
    failure = await api.post("/api/verify", json=body())
    assert failure.status_code == 500 and failure.json()["request_id"] == failure.headers["x-request-id"]
    assert "boom" not in failure.text  # internals stay in the log


# ------------------------------------------------------------------ headers
async def test_security_headers_on_every_kind_of_response(api):
    for path in ("/", "/api/facets", "/health", "/api/nope"):
        headers = (await api.get(path)).headers
        assert headers["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in headers["content-security-policy"], path
        assert headers["x-request-id"]


async def test_no_cors_by_default_so_other_websites_cannot_call_the_api(api):
    preflight = await api.request("OPTIONS", "/api/bookmarks", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "DELETE"})
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in (await api.get("/api/facets", headers={"Origin": "https://evil.example"})).headers


async def test_static_files_and_json_are_compressed(api):
    page = await api.get("/", headers={"Accept-Encoding": "gzip"})
    assert page.headers["content-encoding"] == "gzip" and "Trailbit" in page.text
    listing = await api.get("/api/issues", headers={"Accept-Encoding": "gzip"})
    assert listing.headers.get("content-encoding") == "gzip" and len(listing.json()) == 5
    assert "content-encoding" not in (await api.get("/health", headers={"Accept-Encoding": "gzip"})).headers  # too small to be worth compressing


async def test_static_assets_revalidate_with_an_etag(api):
    first = await api.get("/style.css")
    assert first.headers["cache-control"] == "no-cache" and first.headers["etag"]
    assert (await api.get("/style.css", headers={"If-None-Match": first.headers["etag"]})).status_code == 304


async def test_request_bodies_over_the_limit_get_413(api):
    huge = json.dumps({"github_url": ISSUE, "padding": "x" * 20000})
    refused = await api.post("/api/verify", content=huge, headers={"Content-Type": "application/json"})
    assert refused.status_code == 413


# ------------------------------------------------------------------ discover
async def test_facets(api):
    facets = (await api.get("/api/facets")).json()
    assert facets["languages"] == ["Python", "JavaScript", "TypeScript", "Go", "Rust"] and facets["checklist_length"] == 8
    assert facets["sorts"] == ["updated", "newest", "discussed", "quiet"] and facets["show_token_hint"] is True and "testing" in facets["topics"]


async def test_issue_list_has_no_checklist_and_reports_whether_there_is_more(api):
    response = await api.get("/api/issues")
    cards = response.json()
    assert response.status_code == 200 and [c["id"] for c in cards] == ["3001", "1001", "2001", "1002", "4001"]
    assert all("actionable_checklist" not in c for c in cards) and response.headers["x-has-more"] == "false"
    assert response.headers["cache-control"] == "no-store"
    assert len(response.content) < 2500 * len(cards)


@pytest.mark.parametrize("query,needle", [
    ("q=a", "at least 2 characters"), ("sort=random", "Unknown sort"), ("page=0", ""), ("page=11", ""), ("sort=UPPER1", ""),
    ("language=" + "x" * 31, "at most 30"), ("topic=" + "x" * 61, "at most 60"), ("topic=" + ",".join(str(i) for i in range(13)), "At most 12"),
    ("language=C%22%3B%20DROP", "Unsupported language"),
])
async def test_issue_list_rejects_bad_input(api, query, needle):
    response = await api.get(f"/api/issues?{query}")
    assert response.status_code == 422 and needle in json.dumps(response.json())


async def test_issue_list_passes_filters_sort_and_page_through(api):
    cards = (await api.get("/api/issues?language=Python,Go&topic=testing&sort=newest&page=1&q=  ics  ")).json()
    assert [c["id"] for c in cards] == ["1001"]


async def test_github_trouble_reaches_the_visitor_in_plain_words(api):
    api.engine._github._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))))
    down = await api.get("/api/issues?language=go")
    assert down.status_code == 502 and "Could not reach GitHub" in down.json()["detail"]


# ------------------------------------------------------------------ verify, plan, checklist, guide
async def test_verify_returns_the_health_check(api):
    result = (await api.post("/api/verify", json=body())).json()
    assert (result["health_state"], result["health_score"], result["issue_id"]) == ("healthy", 100, "1001")
    assert [b["label"] for b in result["badges"]] == ["Open for contributions", "Active"] and len(result["issue"]["actionable_checklist"]) == 8


async def test_verify_flags_pull_requests_and_claims(api):
    result = (await api.post("/api/verify", json=body("https://github.com/acme/pyparse/issues/16"))).json()
    labels = [b["label"] for b in result["badges"]]
    assert result["health_state"] == "caution" and "Open pull request (1)" in labels and "Claimed in comments" in labels
    assert result["issue"]["linked_prs"] and result["issue"]["claimed_by"] == ["newbie"]


@pytest.mark.parametrize("url,status", [
    ("https://github.com/acme/pyparse/issues/13", 200), ("https://github.com/acme/pyparse/issues/14", 422),
    ("https://github.com/acme/pyparse/issues/999", 404), ("https://github.com/acme/pyparse", 422), ("https://evil.example/a/b/issues/1", 422),
])
async def test_verify_statuses(api, url, status):
    response = await api.post("/api/verify", json=body(url))
    assert response.status_code == status
    if status == 200:
        assert response.json()["health_state"] == "blocked" and response.json()["badges"][0]["label"] == "Closed"


async def test_requests_with_unknown_fields_or_no_body_are_rejected(api):
    assert (await api.post("/api/verify", json={"github_url": ISSUE, "extra": 1})).status_code == 422
    assert (await api.post("/api/verify", json={})).status_code == 422
    assert (await api.post("/api/verify", content="not json", headers={"Content-Type": "application/json"})).status_code == 422


async def test_plan_and_checklist(api):
    plan = (await api.post("/api/plan", json=body())).json()
    assert plan["repo_full_name"] == "acme/pyparse" and len(plan["actionable_checklist"]) == 8 and "contributing_highlights" not in plan

    fast = await api.get("/api/checklist", params={"github_url": ISSUE, "language": "Python"})
    assert fast.status_code == 200 and fast.json()["actionable_checklist"] == plan["actionable_checklist"]


async def test_checklist_makes_no_github_call_and_validates(api):
    api.engine._github._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("GitHub was called"))))
    assert (await api.get("/api/checklist", params={"github_url": ISSUE})).status_code == 200
    for params in ({"github_url": "https://github.com/acme/pyparse"}, {"github_url": "nope"}, {"github_url": ISSUE, "language": "<script>"}, {}):
        assert (await api.get("/api/checklist", params=params)).status_code == 422


async def test_guide_is_empty_without_tinyfish_and_404s_for_missing_issues(api):
    source = "https://github.com/acme/pyparse/blob/main/.github/CONTRIBUTING.md"
    assert (await api.post("/api/guide", json=body())).json() == {"highlights": [], "source_url": source}
    assert (await api.post("/api/guide", json=body("https://github.com/acme/pyparse/issues/999"))).status_code == 404


# ------------------------------------------------------------------ bookmarks
async def test_a_visitor_saves_lists_and_removes_their_bookmarks(api):
    saved = await api.post("/api/bookmarks", json=body())
    assert saved.status_code == 201 and saved.json()["created"] is True
    bookmark = saved.json()["bookmark"]
    assert set(bookmark) == {"id", "title", "repo_name", "repo_owner", "programming_language", "github_issue_url", "bookmarked_at"}
    assert bookmark["id"] == "1001" and bookmark["bookmarked_at"].endswith("Z")

    again = await api.post("/api/bookmarks", json=body())
    assert again.status_code == 200 and again.json()["created"] is False  # saving twice is harmless
    await api.post("/api/bookmarks", json=body("https://github.com/globex/uikit/issues/21"))
    listed = (await api.get("/api/bookmarks")).json()
    assert [b["id"] for b in listed] == ["2001", "1001"]  # newest first

    assert (await api.delete("/api/bookmarks/1001")).json() == {"status": "deleted", "id": "1001"}
    assert (await api.delete("/api/bookmarks/1001")).status_code == 404
    assert [b["id"] for b in (await api.get("/api/bookmarks")).json()] == ["2001"]


async def test_bookmarks_belong_to_one_visitor(api):
    await api.post("/api/bookmarks", json=body())
    other = httpx.AsyncClient(transport=api._transport, base_url="http://test")  # a second browser: no cookie
    async with other:
        assert (await other.get("/api/bookmarks")).json() == []  # cannot see the first visitor's list
        assert (await other.delete("/api/bookmarks/1001")).status_code == 404  # cannot delete it either
        assert (await other.post("/api/bookmarks", json=body())).json()["created"] is True  # and may save the same issue themselves
    assert [b["id"] for b in (await api.get("/api/bookmarks")).json()] == ["1001"]  # the first visitor's list is untouched


async def test_visitor_cookie_is_httponly_lax_and_secure_behind_https(api):
    cookie = (await api.get("/api/bookmarks")).headers["set-cookie"].lower()
    assert "trailbit_vid=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    secure = await httpx.AsyncClient(transport=api._transport, base_url="http://test").get("/api/bookmarks", headers={"X-Forwarded-Proto": "https"})
    assert "secure" in secure.headers["set-cookie"].lower()
    assert "set-cookie" not in (await api.get("/api/bookmarks")).headers  # a returning visitor is not given a new id


async def test_a_forged_or_malformed_cookie_never_reaches_someone_elses_list(api):
    await api.post("/api/bookmarks", json=body())
    for forged in ("legacy", "x", "../../etc", "a" * 200):
        async with httpx.AsyncClient(transport=api._transport, base_url="http://test", cookies={"trailbit_vid": forged}) as client:
            assert (await client.get("/api/bookmarks")).json() == []


async def test_what_is_stored_comes_from_github_never_from_the_request(api):
    evil = {"github_url": ISSUE, "title": "Official security notice", "github_issue_url": "https://evil.example/login"}
    assert (await api.post("/api/bookmarks", json=evil)).status_code == 422  # the old card payload is refused outright
    assert (await api.post("/api/bookmarks", json=body("https://evil.example/login"))).status_code == 422
    assert (await api.get("/api/bookmarks")).json() == []
    saved = (await api.post("/api/bookmarks", json=body())).json()["bookmark"]
    assert saved["github_issue_url"] == ISSUE and saved["title"] == "Fix timezone parsing in the ICS importer"


@pytest.mark.parametrize("url,status", [("https://github.com/acme/pyparse/issues/999", 404), ("https://github.com/acme/pyparse/issues/14", 422)])
async def test_unsavable_issues_are_refused(api, url, status):
    assert (await api.post("/api/bookmarks", json=body(url))).status_code == status
    assert (await api.get("/api/bookmarks")).json() == []


async def test_bookmark_limit(api, monkeypatch):
    monkeypatch.setenv("MAX_BOOKMARKS", "2")
    for number in (11, 12):
        assert (await api.post("/api/bookmarks", json=body(f"https://github.com/acme/pyparse/issues/{number}"))).status_code == 201
    over = await api.post("/api/bookmarks", json=body("https://github.com/acme/pyparse/issues/15"))
    assert over.status_code == 409 and "up to 2 bookmarks" in over.json()["detail"]
    assert (await api.post("/api/bookmarks", json=body())).status_code == 200  # an existing one is still fine
    await api.delete("/api/bookmarks/1002")
    assert (await api.post("/api/bookmarks", json=body("https://github.com/acme/pyparse/issues/15"))).status_code == 201


async def test_hostile_ids_never_reach_sql(api):
    await api.post("/api/bookmarks", json=body())
    assert (await api.delete("/api/bookmarks/1%27%3B%20DROP%20TABLE%20bookmarks%3B--")).status_code == 422
    assert len((await api.get("/api/bookmarks")).json()) == 1


async def test_saving_while_github_is_rate_limited_explains_why(api):
    rate_limited = httpx.Response(403, json={"message": "API rate limit exceeded"}, headers={"x-ratelimit-remaining": "0"})
    api.engine._github._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: rate_limited))
    limited = await api.post("/api/bookmarks", json=body("https://github.com/acme/pyparse/issues/15"))
    assert limited.status_code == 429 and "rate limit" in limited.json()["detail"] and "retry-after" in limited.headers
    assert (await api.get("/api/bookmarks")).json() == []


async def test_concurrent_saves_of_one_issue_make_exactly_one_row(api):
    import asyncio

    await api.get("/api/bookmarks")  # the browser already has its cookie by the time anyone can double-click a star
    results = await asyncio.gather(*(api.post("/api/bookmarks", json=body()) for _ in range(5)))
    assert sorted(r.status_code for r in results).count(201) == 1 and all(r.status_code in (200, 201) for r in results)
    assert len((await api.get("/api/bookmarks")).json()) == 1
