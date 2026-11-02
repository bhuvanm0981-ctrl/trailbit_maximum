"""Hostile and unlucky input: malformed GitHub data, odd requests, path traversal, a failing database, and load."""

import asyncio
import copy
import time

import httpx
import pytest
from fakes import issue
from sqlalchemy.exc import OperationalError

from backend import database
from backend.routes import meta
from backend.services.github import UpstreamError

pytestmark = pytest.mark.anyio
GOOD = {"https://github.com/acme/pyparse/issues/11": "1001"}
URL = "https://github.com/acme/pyparse/issues/{}".format


def broken(**changes):
    item = issue(9001, 91, "acme", "pyparse", "Broken in one field")
    item.update(changes)
    return item


# ------------------------------------------------------------------ GitHub sends something unexpected
UNREADABLE = {  # one bad field makes that single result unreadable; it must be skipped, never fail the page
    "number is text": {"number": "abc"},
    "no id": {"id": None},
    "no link": {"html_url": None},
    "link is a number": {"html_url": 5},
    "dates missing": {"created_at": None, "updated_at": None},
    "date is garbage": {"updated_at": "not a date", "created_at": "not a date"},
    "comment count is text": {"comments": "many"},
    "repository is not a repo": {"repository_url": "https://api.github.com/nope"},
    "repository missing": {"repository_url": None},
}
READABLE = {  # odd, but a card can still be made
    "no title": {"title": None},
    "title is spaces": {"title": "    "},
    "no body, user, labels, assignees or count": {"body": None, "user": None, "labels": None, "assignees": None, "comments": None},
    "labels is a string": {"labels": "bug"},
    "labels with nulls and numbers": {"labels": [None, {"name": None}, {"name": 5}, "x", {"name": "ok"}]},
    "assignees with nulls": {"assignees": [None, {"login": None}, {"login": "real"}]},
    "body is a number": {"body": 12345},
    "emoji, control characters and a huge body": {"title": "Fix \U0001f4a5 \x07 bug", "body": "word " * 200_000},
}


@pytest.mark.parametrize("name", UNREADABLE)
async def test_one_unreadable_search_result_is_skipped_not_fatal(make_engine, fake, name):
    fake.search["python"] = [broken(**UNREADABLE[name]), issue(1001, 11, "acme", "pyparse", "A good issue")]
    page = await make_engine().list_issues(language="python")
    assert [c.id for c in page.cards] == ["1001"]


@pytest.mark.parametrize("name", READABLE)
async def test_odd_but_usable_search_results_still_make_cards(make_engine, fake, name):
    fake.search["python"] = [broken(**READABLE[name])]
    page = await make_engine().list_issues(language="python")
    assert len(page.cards) == 1 and page.cards[0].title and len(page.cards[0].context_summary) <= 700
    assert all(isinstance(topic, str) for topic in page.cards[0].topics)


@pytest.mark.parametrize("sort", ["updated", "newest", "discussed", "quiet"])
async def test_mixed_types_never_break_sorting(make_engine, fake, sort):
    fake.search["python"] = [broken(updated_at=None, created_at="2026-01-01T00:00:00Z", comments=None, id=1),
                             broken(updated_at="2026-02-01T00:00:00Z", comments=3, id=2), broken(comments="seven", id=3)]
    page = await make_engine().list_issues(language="python", sort=sort)
    assert {c.id for c in page.cards} <= {"1", "2"}  # the item whose comment count is text is dropped; the rest are ordered


async def test_topic_filter_survives_non_text_fields(make_engine, fake):
    fake.search["python"] = [broken(labels=[{"name": 5}, {"name": "testing"}], title=None, body=7, id=4)]
    assert [c.id for c in (await make_engine().list_issues(language="python", topic="testing")).cards] == ["4"]


async def test_a_page_where_every_result_is_unreadable_is_just_empty(make_engine, fake):
    fake.search["python"] = [broken(number="x", id=i) for i in range(5)]
    assert (await make_engine().list_issues(language="python")).cards == []


MUTATIONS = {
    "number is text": {"number": "x"},
    "no html_url": {"html_url": None},
    "comments is text": {"comments": "lots"},
    "no id": {"id": None},
}


@pytest.mark.parametrize("name", MUTATIONS)
async def test_an_unreadable_issue_is_a_clear_502_not_a_crash(api, fake, name):
    fake.issues[("acme", "pyparse", 11)] = copy.deepcopy(fake.issues[("acme", "pyparse", 11)]) | MUTATIONS[name]
    response = await api.post("/api/verify", json={"github_url": URL(11)})
    assert response.status_code == 502 and "could not read" in response.json()["detail"]


@pytest.mark.parametrize("field,value", [("profile", []), ("timeline", {"message": "oops"}), ("comments", {"message": "oops"}), ("repo", {"language": None, "owner": None, "name": None, "archived": None})])
async def test_odd_side_data_never_fails_a_check(api, fake, field, value):
    if field == "profile":
        fake.profiles[("acme", "pyparse")] = value
    elif field == "timeline":
        fake.timelines[("acme", "pyparse", 11)] = value
    elif field == "comments":
        fake.comments[("acme", "pyparse", 11)] = value
    else:
        fake.repos[("acme", "pyparse")] = value
    response = await api.post("/api/verify", json={"github_url": URL(11)})
    assert response.status_code == 200, response.text
    assert response.json()["issue"]["programming_language"] in ("Python", "Unknown")


async def test_garbage_comments_and_timeline_entries_are_ignored(api, fake):
    fake.comments[("acme", "pyparse", 11)] = [None, 5, "x", {"user": None, "body": 7, "created_at": None}, {"user": {"login": 3}, "body": None, "created_at": "garbage"}]
    fake.timelines[("acme", "pyparse", 11)] = [None, "x", {"event": "cross-referenced", "source": None}, {"event": "cross-referenced", "source": {"issue": 5}}]
    response = await api.post("/api/verify", json={"github_url": URL(11)})
    assert response.status_code == 200 and response.json()["issue"]["claimed_by"] == []


async def test_only_github_links_are_kept_as_linked_pull_requests(api, fake):
    def pull(url):
        return {"event": "cross-referenced", "source": {"issue": {"html_url": url, "state": "open", "pull_request": {"url": "x"}}}}

    fake.timelines[("acme", "pyparse", 11)] = [pull("javascript:alert(1)"), pull("https://evil.example/pull/1"), pull("http://github.com/a/b/pull/1"), pull("https://github.com/a/b/pull/2")]
    assert (await api.post("/api/verify", json={"github_url": URL(11)})).json()["issue"]["linked_prs"] == ["https://github.com/a/b/pull/2"]


# ------------------------------------------------------------------ odd requests
@pytest.mark.parametrize("path", [
    "/../backend/main.py", "/%2e%2e/backend/main.py", "/..%2fbackend%2fmain.py", "/%2e%2e%2f%2e%2e%2f.env", "/js/../../.env", "/.env", "/.git/config",
    "/trailbit.db", "/requirements.txt", "/package.json", "/backend/main.py", "/tests/conftest.py", "/node_modules/.package-lock.json", "/%00", "/js/%2e%2e/%2e%2e/README.md",
    "/..\\backend\\main.py", "/js\\..\\..\\.env", "//etc/passwd", "/%252e%252e/%252e%252e/.env",
])
async def test_static_files_cannot_be_escaped(api, path):
    response = await api.get(path)
    assert response.status_code in (400, 404), (path, response.status_code)
    assert "BodyLimitMiddleware" not in response.text and "DATABASE_URL" not in response.text and "sqlite" not in response.text.lower()


@pytest.mark.parametrize("method", ["PUT", "PATCH", "TRACE", "DELETE", "OPTIONS"])
async def test_wrong_methods_are_refused_cleanly(api, method):
    response = await api.request(method, "/api/issues")
    assert response.status_code in (200, 405) and response.status_code != 500


@pytest.mark.parametrize("query", [
    "q=%00", "q=%F0%9F%92%A9%F0%9F%92%A9", "q=%", "q=%ZZ", "q=%C3%28", "language=", "topic=%2C%2C%2C", "page=abc", "page=1e3", "page=-1", "page=99999999999999999999",
    "sort=updated&sort=newest", "q=" + "a" * 101, "q=a+b+c&q=d+e", "language=Python&language=" + "x" * 31, "q=repo:foo+is:closed+-label:bug", 'q="unterminated', "q=%26%3D%3F%23",
])
async def test_odd_query_strings_never_cause_a_server_error(api, query):
    response = await api.get(f"/api/issues?{query}")
    assert response.status_code < 500, (query, response.status_code, response.text[:200])
    assert response.headers["content-type"].startswith("application/json")


async def test_a_very_long_url_is_refused_or_answered_not_crashed(api):
    assert (await api.get("/api/issues?q=" + "a" * 20_000)).status_code in (404, 414, 422)


@pytest.mark.parametrize("payload,content_type", [
    (b"\xff\xfe\x00\x00", "application/json"),
    (b"[" * 5000 + b"]" * 5000, "application/json"),
    (b'{"github_url": ' + b'"x"' * 10 + b"}", "application/json"),
    (b"null", "application/json"), (b"[]", "application/json"), (b'"https://github.com/a/b/issues/1"', "application/json"),
    (b'{"github_url": null}', "application/json"), (b'{"github_url": ["x"]}', "application/json"), (b'{"github_url": 5}', "application/json"),
    (b'{"github_url": "https://github.com/acme/pyparse/issues/11"}', "text/plain"),
    (b"github_url=https://github.com/acme/pyparse/issues/11", "application/x-www-form-urlencoded"),
    (b"", "application/json"), (b"{", "application/json"),
])
@pytest.mark.parametrize("endpoint", ["/api/verify", "/api/plan", "/api/guide", "/api/bookmarks"])
async def test_odd_request_bodies_are_422_never_500(api, endpoint, payload, content_type):
    response = await api.post(endpoint, content=payload, headers={"Content-Type": content_type})
    assert response.status_code in (400, 413, 415, 422), (endpoint, payload[:30], response.status_code, response.text[:200])


@pytest.mark.parametrize("bad", ["https://github.com/acme/pyparse/issues/11\n", "https://github.com/acme/pyparse/issues/11 ", " https://github.com/acme/pyparse/issues/11",
                                 "https://github.com/acme/pyparse/issues/11?x=1", "https://github.com/acme/pyparse/issues/11#c", "https://github.com:443/acme/pyparse/issues/11",
                                 "https://user@github.com/acme/pyparse/issues/11", "HTTPS://GITHUB.COM/acme/pyparse/issues/11", "https://github.com/acme/pyparse/issues/011"])
async def test_url_lookalikes_never_reach_github_wrongly(api, fake, bad):
    response = await api.post("/api/verify", json={"github_url": bad})
    assert response.status_code in (200, 404, 422)  # accepted only if it normalises to the same issue
    if response.status_code == 200:
        assert response.json()["issue_id"] in ("1001", "1005")  # 011 normalises to 11's repo; never some other repo
    assert all(r.url.path.startswith(("/repos/acme/pyparse", "/search")) for r in fake.requests)


@pytest.mark.parametrize("raw", ["/api/bookmarks/%00", "/api/bookmarks/%F0%9F%92%A9", "/api/bookmarks/" + "9" * 41, "/api/bookmarks/a%2Fb", "/api/bookmarks/..%2F..%2Fx", "/api/bookmarks/%20"])
async def test_odd_bookmark_ids_are_refused_or_not_found(api, raw):
    assert (await api.delete(raw)).status_code in (404, 405, 422)  # 405: an encoded slash makes it a different path


@pytest.mark.parametrize("cookie", ["", "trailbit_vid=", "trailbit_vid=" + "a" * 10_000, "trailbit_vid=a b", "trailbit_vid=%C3%A9%C3%A9", "trailbit_vid=x; trailbit_vid=y", "junk"])
async def test_odd_cookies_just_make_a_new_visitor(api, cookie):
    response = await api.get("/api/bookmarks", headers={"Cookie": cookie})
    assert response.status_code == 200 and response.json() == []


async def test_a_spoofed_request_id_cannot_inject_headers(api):
    response = await api.get("/health", headers={"X-Request-ID": "abc123\r\nSet-Cookie: x=1"})
    assert "set-cookie" not in response.headers and "\r" not in response.headers["x-request-id"]


# ------------------------------------------------------------------ the database has a bad day
async def test_ready_reports_503_when_the_database_is_down(api, monkeypatch):
    class Down:
        async def __aenter__(self):
            raise OperationalError("select 1", {}, Exception("disk I/O error"))

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(meta, "async_session", lambda: Down())
    response = await api.get("/ready")
    assert response.status_code == 503 and response.json()["database"] == "error" and "disk" not in response.text
    assert (await api.get("/health")).status_code == 200  # being unready must not fail the platform's liveness probe


async def test_a_database_failure_is_json_with_a_request_id_not_a_crash(api, monkeypatch):
    class Boom:
        def __init__(self, *args, **kwargs):
            raise OperationalError("insert", {}, Exception("database is locked"))

    monkeypatch.setattr(database, "Bookmark", Boom)
    monkeypatch.setattr("backend.routes.bookmarks.Bookmark", Boom)
    response = await api.post("/api/bookmarks", json={"github_url": URL(11)})
    assert response.status_code == 500 and response.json()["request_id"] and "locked" not in response.text
    assert (await api.get("/api/facets")).status_code == 200  # and the app carries on


# ------------------------------------------------------------------ GitHub is slow or the budget is spent mid-request
async def test_upstream_failures_are_never_cached_as_results(api, fake):
    fake.down = True
    assert (await api.post("/api/verify", json={"github_url": URL(11)})).status_code == 502
    fake.down = False
    assert (await api.post("/api/verify", json={"github_url": URL(11)})).status_code == 200  # recovers at once


async def test_a_github_error_on_the_side_calls_does_not_fail_the_check(api, fake):
    original = fake._handle

    async def flaky(request):
        if request.url.path.endswith(("/timeline", "/community/profile")):
            return httpx.Response(500, json={"message": "boom"})
        return await original(request)

    fake.client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(flaky))
    api.engine._github._client = fake.client()
    response = await api.post("/api/verify", json={"github_url": URL(11)})
    assert response.status_code == 200 and response.json()["issue"]["linked_prs"] == []


async def test_an_error_in_the_main_issue_call_surfaces_as_upstream(api, fake):
    api.engine._github._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"message": "boom"})))
    response = await api.post("/api/verify", json={"github_url": URL(11)})
    assert response.status_code == 502 and "try again" in response.json()["detail"].lower()
    with pytest.raises(UpstreamError):
        await api.engine.research_issue(URL(11))


# ------------------------------------------------------------------ load
async def test_a_burst_of_mixed_traffic_has_no_errors_and_few_github_calls(api, fake):
    """300 requests at once from 30 visitors: lists, checks, plans, checklists, saves, reads and deletes."""
    visitors = [httpx.AsyncClient(transport=api._transport, base_url="http://test") for _ in range(30)]
    try:
        for v in visitors:
            await v.get("/api/bookmarks")  # each gets a cookie first, as a browser does
        started = time.perf_counter()
        jobs = []
        for i, v in enumerate(visitors):
            number = (11, 12, 15, 16)[i % 4]
            jobs += [v.get("/api/issues"), v.get("/api/issues?language=python&sort=newest"), v.post("/api/verify", json={"github_url": URL(number)}),
                     v.post("/api/plan", json={"github_url": URL(number)}), v.post("/api/guide", json={"github_url": URL(number)}),
                     v.get("/api/checklist", params={"github_url": URL(number)}), v.post("/api/bookmarks", json={"github_url": URL(number)}),
                     v.get("/api/bookmarks"), v.get("/api/facets"), v.get("/ready")]
        responses = await asyncio.gather(*jobs)
        elapsed = time.perf_counter() - started
        statuses = [r.status_code for r in responses]
        assert len(responses) == 300 and all(s in (200, 201) for s in statuses), sorted({s for s in statuses})
        assert elapsed < 20, f"300 requests took {elapsed:.1f}s"
        # Everything identical was shared: 5 languages for the default list + 1 for the python one, and one research per issue.
        assert fake.calls["/search/issues"] == 6, fake.calls["/search/issues"]
        for number in (11, 12, 15, 16):
            assert fake.calls[f"/repos/acme/pyparse/issues/{number}"] == 1
        # And each visitor ended with exactly the one bookmark they saved, in the right database row.
        for i, v in enumerate(visitors):
            saved = (await v.get("/api/bookmarks")).json()
            assert [b["github_issue_url"] for b in saved] == [URL((11, 12, 15, 16)[i % 4])]
    finally:
        for v in visitors:
            await v.aclose()


async def test_many_distinct_searches_cannot_grow_memory_or_spend_unbounded_github_calls(make_engine, fake):
    engine = make_engine(search_budget=8)  # what an unauthenticated deployment gets
    ok = errors = 0
    for i in range(60):
        try:
            await engine.list_issues(language="go", query=f"distinct query {i}")
            ok += 1
        except UpstreamError:
            errors += 1
    assert ok == 8 and errors == 52 and fake.calls["/search/issues"] == 8  # the 9th distinct search in a minute is refused locally
    assert len(engine._search_cache) <= 256
