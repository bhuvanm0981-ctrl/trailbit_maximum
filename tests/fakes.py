"""A fake GitHub, served through httpx.MockTransport. Shared by the pytest suite and the browser tests."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx


def iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue(id_, number, owner, repo, title, body="", labels=("good first issue",), comments=0, assignees=(), locked=False,
          updated=3, created=20, state="open", user="author1", pull=False):
    data = {
        "id": id_, "number": number, "title": title, "body": body, "state": state, "locked": locked,
        "comments": comments, "labels": [{"name": n} for n in labels],
        "assignees": [{"login": a} for a in assignees], "user": {"login": user},
        "html_url": f"https://github.com/{owner}/{repo}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{owner}/{repo}",
        "created_at": iso(created), "updated_at": iso(updated),
    }
    if pull:
        data["pull_request"] = {"url": "x"}
    return data


def _comments(count, newest_days_ago=1.0):
    """`count` comments, oldest first, the newest `newest_days_ago` days old."""
    return [{"user": {"login": f"user{i % 7}"}, "body": f"comment {i}", "created_at": iso(newest_days_ago + (count - 1 - i) * 0.1)} for i in range(count)]


def build_data():
    search = {
        "python": [
            issue(1001, 11, "acme", "pyparse", "Fix timezone parsing in the ICS importer",
                  body="## Problem\nDates shift by an hour. See `src/pyparse/ics.py` and tests/test_ics.py.\n\n<!-- template -->\n```py\nprint('x')\n```",
                  labels=("good first issue", "bug", "testing", "stage/040-covered-by-pr"), comments=4, updated=2, created=9),
            issue(1002, 12, "acme", "pyparse", "Document the config file", body="Add docs.", labels=("good first issue", "documentation"),
                  comments=1, assignees=("maint1",), updated=40),
        ],
        "javascript": [issue(2001, 21, "globex", "uikit", "Add keyboard navigation to Dropdown", body="Needs a11y work in packages/ui/Dropdown.jsx",
                             labels=("good first issue", "accessibility"), comments=2, updated=5)],
        "typescript": [issue(3001, 31, "initech", "tsq", "Fix select inference", body="x" * 3000,
                             labels=("good first issue", "typing", "performance"), comments=9, updated=1)],
        "go": [issue(4001, 41, "umbrella", "gopool", "Add context cancellation to Shutdown", body="Shutdown() blocks forever.",
                     labels=("good first issue", "help wanted"), comments=0, locked=True, updated=90)],
        "rust": [],
    }
    issues = {
        ("acme", "pyparse", 11): search["python"][0],
        ("acme", "pyparse", 12): search["python"][1],
        ("globex", "uikit", 21): search["javascript"][0],
        ("umbrella", "gopool", 41): search["go"][0],
        ("acme", "pyparse", 13): issue(1003, 13, "acme", "pyparse", "Already fixed", state="closed", updated=1),
        ("acme", "pyparse", 14): issue(1004, 14, "acme", "pyparse", "A pull request", pull=True),
        ("acme", "pyparse", 15): issue(1005, 15, "acme", "pyparse", "Quiet issue with no comments", comments=0, created=5, updated=5),
        ("acme", "pyparse", 16): issue(1006, 16, "acme", "pyparse", "Someone is on it", comments=3, updated=2),
        ("acme", "pyparse", 17): issue(1007, 17, "acme", "pyparse", "Long thread", comments=61, updated=1),
        ("acme", "pyparse", 18): issue(1008, 18, "acme", "pyparse", "Longer thread", comments=70, updated=1),
        ("acme", "pyparse", 19): issue(1009, 19, "acme", "pyparse", "Old claim", comments=1, updated=1),
    }
    repos = {
        ("acme", "pyparse"): {"name": "pyparse", "owner": {"login": "acme"}, "language": "Python", "archived": False},
        ("globex", "uikit"): {"name": "uikit", "owner": {"login": "globex"}, "language": "JavaScript", "archived": False},
        ("umbrella", "gopool"): {"name": "gopool", "owner": {"login": "umbrella"}, "language": "Go", "archived": True},
    }
    profiles = {("acme", "pyparse"): {"files": {"contributing": {"html_url": "https://github.com/acme/pyparse/blob/main/.github/CONTRIBUTING.md"}}}}
    comments = {
        ("acme", "pyparse", 11): _comments(4),
        ("acme", "pyparse", 16): [
            {"user": {"login": "dependabot[bot]"}, "body": "I'll fix this", "created_at": iso(9)},
            {"user": {"login": "newbie"}, "body": "Hi! I'd like to work on this, can I take it?", "created_at": iso(5)},
            {"user": {"login": "maint1"}, "body": "Go ahead", "created_at": iso(4)},
        ],
        ("acme", "pyparse", 17): _comments(61),
        ("acme", "pyparse", 18): _comments(70),
        ("acme", "pyparse", 19): [{"user": {"login": "olduser"}, "body": "I'll work on this", "created_at": iso(200)}],
    }
    timelines = {
        ("acme", "pyparse", 16): [
            {"event": "labeled"},
            {"event": "cross-referenced", "source": {"issue": {"html_url": "https://github.com/acme/pyparse/pull/99", "state": "open", "pull_request": {"url": "x"}}}},
            {"event": "cross-referenced", "source": {"issue": {"html_url": "https://github.com/acme/pyparse/pull/50", "state": "closed", "pull_request": {"url": "x"}}}},
            {"event": "cross-referenced", "source": {"issue": {"html_url": "https://github.com/acme/pyparse/issues/3", "state": "open"}}},
        ],
    }
    return search, issues, repos, profiles, comments, timelines


class FakeGitHub:
    """Callable httpx handler that records every request. Switches: search_rate_limited, reject_token, down, latency."""

    def __init__(self):
        self.search, self.issues, self.repos, self.profiles, self.comments, self.timelines = build_data()
        self.calls = Counter()
        self.requests = []
        self.search_rate_limited = False
        self.reject_token = False
        self.down = False
        self.latency = 0.0
        self.pages = {}  # (language, page) -> items; overrides the default single page, to test "load more"

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.latency:
            await asyncio.sleep(self.latency)
        if self.down:
            raise httpx.ConnectError("offline")
        path = request.url.path
        self.requests.append(request)
        self.calls[path] += 1
        if self.reject_token and request.headers.get("authorization"):
            return httpx.Response(401, json={"message": "Bad credentials"})

        if path == "/search/issues":
            if self.search_rate_limited:
                reset = int(datetime.now(UTC).timestamp()) + 120
                return httpx.Response(403, json={"message": "API rate limit exceeded for 1.2.3.4."},
                                      headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)})
            params = request.url.params
            lang = params["q"].split('language:"')[1].split('"')[0]
            page = int(params.get("page", 1))
            items = self.pages.get((lang, page)) if (lang, page) in self.pages else (self.search.get(lang, []) if page == 1 else [])
            headers = {"x-ratelimit-resource": "search", "x-ratelimit-remaining": "9", "x-ratelimit-limit": "10", "x-ratelimit-reset": "1"}
            return httpx.Response(200, json={"total_count": len(items), "incomplete_results": False, "items": items}, headers=headers)

        parts = path.strip("/").split("/")
        if parts[0] != "repos" or len(parts) < 3:
            return httpx.Response(404, json={"message": "Not Found"})
        owner, repo = parts[1], parts[2]
        not_found = httpx.Response(404, json={"message": "Not Found"})
        core = {"x-ratelimit-resource": "core", "x-ratelimit-remaining": "58", "x-ratelimit-limit": "60", "x-ratelimit-reset": "1"}
        if len(parts) == 3:
            data = self.repos.get((owner, repo))
            return httpx.Response(200, json=data, headers=core) if data else not_found
        if parts[3] == "community":
            data = self.profiles.get((owner, repo))
            return httpx.Response(200, json=data, headers=core) if data else not_found
        if parts[3] == "issues":
            number = int(parts[4])
            if len(parts) == 5:
                data = self.issues.get((owner, repo, number))
                return httpx.Response(200, json=data, headers=core) if data else not_found
            if parts[5] == "timeline":
                return httpx.Response(200, json=self.timelines.get((owner, repo, number), []), headers=core)
            everything = self.comments.get((owner, repo, number), [])
            per_page = int(request.url.params.get("per_page", 30))
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=everything[(page - 1) * per_page: page * per_page], headers=core)
        return not_found
