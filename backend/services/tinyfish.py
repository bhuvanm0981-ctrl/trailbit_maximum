"""TinyFishEngine: the live research layer, backed by the public GitHub REST API.

Discovery uses the issue search API (``label:"good first issue"``); verification and plans use
the issue, repository, comments and community-profile endpoints. Responses are cached briefly
and identical in-flight requests are shared, because the unauthenticated limits are small
(10 searches a minute, 60 other requests an hour). Set ``GITHUB_TOKEN`` in ``.env`` to raise them.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Hashable, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from ..models.response import IssueCard
from ..utils import (
    activity_from_days,
    build_checklist,
    days_since,
    estimate_difficulty,
    extract_paths,
    parse_github_url,
    summarize_body,
)

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger("trailbit.github")

GITHUB_API = "https://api.github.com"
GOOD_FIRST_LABEL = "good first issue"
MAX_RESULTS = 30
COMMENT_PAGE_SIZE = 5

# Display name -> GitHub `language:` qualifier. Other names are passed through as typed.
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "Python": "python",
    "JavaScript": "javascript",
    "TypeScript": "typescript",
    "Go": "go",
    "Rust": "rust",
}
_CANONICAL_LANGUAGE = {name.lower(): name for name in SUPPORTED_LANGUAGES}
_LANGUAGE_NAME = re.compile(r"[A-Za-z0-9+#. -]{1,30}")

# Offered as topic filters. They are matched against an issue's labels, title and description.
TOPIC_SUGGESTIONS: List[str] = [
    "documentation",
    "testing",
    "bug",
    "cli",
    "api",
    "ui",
    "accessibility",
    "performance",
    "refactor",
    "security",
    "typing",
    "help wanted",
]

FilterValues = Optional[Union[str, Sequence[str]]]


# --------------------------------------------------------------------------- errors
class IssueNotFoundError(LookupError):
    """GitHub has no issue at the requested URL."""


class UpstreamError(Exception):
    """GitHub could not be reached or returned an error we cannot work around."""

    def __init__(self, message: str, *, status_code: int = 502, headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = headers or {}


class RateLimitError(UpstreamError):
    """GitHub's rate limit is exhausted."""

    def __init__(self, message: str, *, retry_after: int = 60) -> None:
        super().__init__(message, status_code=429, headers={"Retry-After": str(retry_after)})


# --------------------------------------------------------------------------- GitHub client
class _GitHubClient:
    """Thin async wrapper: auth header, error mapping, and a fallback when the token is rejected."""

    def __init__(self, token: Optional[str], client: Optional[httpx.AsyncClient] = None) -> None:
        self._token = (token or "").strip() or None
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "trailbit",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = await self._send(path, params)
        if response.status_code == 401 and self._token:
            logger.warning("GitHub rejected GITHUB_TOKEN; continuing without authentication.")
            self._token = None
            response = await self._send(path, params)
        return self._parse(response)

    async def _send(self, path: str, params: Optional[Dict[str, Any]]) -> httpx.Response:
        try:
            return await self._client.get(f"{GITHUB_API}{path}", params=params, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise UpstreamError("GitHub took too long to respond. Try again in a moment.", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach GitHub. Check your connection and try again.", status_code=502) from exc

    def _parse(self, response: httpx.Response) -> Any:
        code = response.status_code
        if code == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise UpstreamError("GitHub returned a response Trailbit could not read.") from exc
        if code in (404, 410):
            raise IssueNotFoundError("GitHub has nothing at that address.")

        message = _error_message(response)
        limited = (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in message.lower()
            or bool(response.headers.get("retry-after"))
        )
        if code in (403, 429) and limited:
            raise self._rate_limit_error(response)
        if code == 422:
            raise ValueError(f"GitHub could not run that search: {message}")
        raise UpstreamError(f"GitHub returned an error ({code}). Try again in a moment.")

    def _rate_limit_error(self, response: httpx.Response) -> RateLimitError:
        now = time.time()
        retry_after = 60
        when = ""
        reset = response.headers.get("x-ratelimit-reset", "")
        header_retry = response.headers.get("retry-after", "")
        if reset.isdigit():
            retry_after = int(reset) - int(now)
            when = f" (resets around {datetime.fromtimestamp(int(reset), tz=timezone.utc):%H:%M} UTC)"
        elif header_retry.isdigit():
            retry_after = int(header_retry)
        retry_after = max(1, min(retry_after, 3600))
        hint = "" if self.authenticated else " Add a GITHUB_TOKEN to .env for much higher limits."
        return RateLimitError(f"GitHub's rate limit is used up for now{when}.{hint}", retry_after=retry_after)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            return body["message"]
    except ValueError:
        pass
    return response.reason_phrase or "unknown error"


# --------------------------------------------------------------------------- cache
class _TTLCache:
    """Small async cache. Concurrent callers for one key share a single in-flight request,
    and failures are never cached."""

    def __init__(self, ttl: float, max_items: int = 256) -> None:
        self._ttl = ttl
        self._max_items = max_items
        self._entries: Dict[Hashable, Tuple[float, "asyncio.Future[Any]"]] = {}

    async def get_or_create(self, key: Hashable, factory: Callable[[], Awaitable[Any]]) -> Any:
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry and entry[0] > now:
            return await asyncio.shield(entry[1])

        task = asyncio.ensure_future(factory())
        self._entries[key] = (now + self._ttl, task)

        def _forget_failures(done: "asyncio.Future[Any]") -> None:
            if done.cancelled() or done.exception() is not None:
                current = self._entries.get(key)
                if current and current[1] is done:
                    del self._entries[key]

        task.add_done_callback(_forget_failures)
        self._prune(now)
        return await asyncio.shield(task)

    def _prune(self, now: float) -> None:
        if len(self._entries) <= self._max_items:
            return
        for key in [k for k, (expires, _) in self._entries.items() if expires <= now]:
            del self._entries[key]
        while len(self._entries) > self._max_items:
            del self._entries[next(iter(self._entries))]


# --------------------------------------------------------------------------- mapping helpers
def _as_list(values: FilterValues) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values] if values.strip() else []
    return [v for v in values if isinstance(v, str) and v.strip()]


def _label_names(issue: Dict[str, Any]) -> List[str]:
    return [label["name"] for label in issue.get("labels") or [] if isinstance(label, dict) and label.get("name")]


def _handles(issue: Dict[str, Any], commenters: Sequence[str] = ()) -> List[str]:
    """Assignees, then the author, then recent commenters. Bots are skipped."""
    ordered: List[str] = [a.get("login", "") for a in issue.get("assignees") or [] if isinstance(a, dict)]
    ordered.append(((issue.get("user") or {}).get("login")) or "")
    ordered.extend(commenters)
    seen: List[str] = []
    for login in ordered:
        if login and not login.endswith("[bot]") and login not in seen:
            seen.append(login)
    return seen[:5]


def _repo_from_api_url(repository_url: str) -> Tuple[str, str]:
    parts = [p for p in urlparse(repository_url).path.split("/") if p]
    if len(parts) < 3 or parts[0] != "repos":
        raise UpstreamError("GitHub returned a search result Trailbit could not place in a repository.")
    return parts[1], parts[2]


def _matches_topics(issue: Dict[str, Any], topics: Sequence[str]) -> bool:
    haystack = " ".join([issue.get("title") or "", *_label_names(issue), (issue.get("body") or "")[:2000]]).lower()
    return any(topic in haystack for topic in topics)


def _clean_query(query: Optional[str]) -> str:
    printable = "".join(ch for ch in (query or "") if ch.isprintable())
    return re.sub(r"\s+", " ", printable).strip()


def _build_card(
    issue: Dict[str, Any],
    *,
    owner: str,
    repo: str,
    language: str,
    last_comment_date: str,
    handles: List[str],
    contributing_url: str,
    locked: bool,
) -> IssueCard:
    number = int(issue["number"])
    labels = _label_names(issue)
    body = issue.get("body") or ""
    comment_count = int(issue.get("comments") or 0)
    assignees = [a for a in issue.get("assignees") or [] if isinstance(a, dict) and a.get("login")]

    return IssueCard(
        id=str(issue["id"]),
        title=(issue.get("title") or "").strip() or f"Issue #{number}",
        repo_name=repo,
        repo_owner=owner,
        programming_language=language or "Unknown",
        topics=[label for label in labels if label.lower() != GOOD_FIRST_LABEL][:5],
        github_issue_url=issue["html_url"],
        contributing_guidelines_url=contributing_url,
        status_metrics={
            "is_locked": locked,
            "activity_indicator": activity_from_days(days_since(last_comment_date)),
            "last_comment_date": last_comment_date,
        },
        difficulty_rating=estimate_difficulty(labels, comment_count, len(body)),
        context_summary=summarize_body(body),
        actionable_checklist=build_checklist(owner, repo, number, language),
        affected_paths=extract_paths(body),
        active_handles=handles,
        state="closed" if issue.get("state") == "closed" else "open",
        assignee_count=len(assignees),
        comment_count=comment_count,
    )


def _contribute_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}/contribute"


# --------------------------------------------------------------------------- engine
class TinyFishEngine:
    """Live GitHub research: discovery by search, and per-issue research by URL."""

    def __init__(
        self,
        token: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        search_ttl: float = 300.0,
        issue_ttl: float = 600.0,
    ) -> None:
        self._github = _GitHubClient(os.getenv("GITHUB_TOKEN", "") if token is None else token, client)
        self._search_cache = _TTLCache(search_ttl)
        self._issue_cache = _TTLCache(issue_ttl)

    @property
    def authenticated(self) -> bool:
        return self._github.authenticated

    async def aclose(self) -> None:
        await self._github.aclose()

    def facets(self) -> Dict[str, Any]:
        return {
            "languages": list(SUPPORTED_LANGUAGES),
            "topics": list(TOPIC_SUGGESTIONS),
            "github_authenticated": self.authenticated,
        }

    # ---- discovery -------------------------------------------------------------------------
    async def list_issues(
        self, language: FilterValues = None, topic: FilterValues = None, query: Optional[str] = None
    ) -> List[IssueCard]:
        """Open "good first issue" issues from GitHub, newest activity first.

        One search runs per language (the search API does not report an issue's language, so
        the language is known from the query itself). Topics are matched against labels, title
        and description. Results are cached for a few minutes.
        """
        languages = self._resolve_languages(language)
        topics = [t.strip().lower() for t in _as_list(topic)]
        text = _clean_query(query)
        per_page = 30 if topics else min(30, max(6, math.ceil(MAX_RESULTS / len(languages))))

        outcomes = await asyncio.gather(
            *(self._search(qualifier, text, per_page) for _, qualifier in languages), return_exceptions=True
        )

        found: List[Tuple[str, Dict[str, Any]]] = []
        first_error: Optional[BaseException] = None
        for (display, _), outcome in zip(languages, outcomes):
            if isinstance(outcome, (UpstreamError, ValueError)):
                first_error = first_error or outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                found.extend((display, item) for item in outcome)
        if not found and first_error:
            raise first_error

        if topics:
            found = [(lang, item) for lang, item in found if _matches_topics(item, topics)]
        found.sort(key=lambda pair: pair[1].get("updated_at") or "", reverse=True)

        cards: List[IssueCard] = []
        for display, item in found[:MAX_RESULTS]:
            owner, repo = _repo_from_api_url(item["repository_url"])
            cards.append(
                _build_card(
                    item,
                    owner=owner,
                    repo=repo,
                    language=display,
                    # Search results carry no comment timestamps, so last activity stands in here.
                    # research_issue() refines it with the real last comment.
                    last_comment_date=(item.get("updated_at") or item["created_at"])[:10],
                    handles=_handles(item),
                    contributing_url=_contribute_url(owner, repo),
                    locked=bool(item.get("locked")),
                )
            )
        return cards

    @staticmethod
    def _resolve_languages(language: FilterValues) -> List[Tuple[str, str]]:
        requested = _as_list(language)
        if not requested:
            return list(SUPPORTED_LANGUAGES.items())
        resolved: List[Tuple[str, str]] = []
        for raw in requested:
            value = raw.strip()
            if not _LANGUAGE_NAME.fullmatch(value):
                raise ValueError(f"Unsupported language name: {value[:30]!r}")
            display = _CANONICAL_LANGUAGE.get(value.lower(), value)
            pair = (display, SUPPORTED_LANGUAGES.get(display, value.lower()))
            if pair not in resolved:
                resolved.append(pair)
        return resolved

    async def _search(self, language_qualifier: str, text: str, per_page: int) -> List[Dict[str, Any]]:
        async def fetch() -> List[Dict[str, Any]]:
            parts = [
                f'label:"{GOOD_FIRST_LABEL}"',
                "is:issue",
                "is:open",
                "archived:false",
                f'language:"{language_qualifier}"',
            ]
            if text:
                parts.append(text)
            data = await self._github.get_json(
                "/search/issues",
                {"q": " ".join(parts), "sort": "updated", "order": "desc", "per_page": per_page},
            )
            return list(data.get("items") or [])

        return await self._search_cache.get_or_create(("search", language_qualifier, text.lower(), per_page), fetch)

    # ---- one issue -------------------------------------------------------------------------
    async def research_issue(self, url: str) -> IssueCard:
        """Research one GitHub issue URL live and return its IssueCard.

        Raises ``ValueError`` for a malformed or non-issue URL, ``IssueNotFoundError`` when
        GitHub has no such issue, and ``UpstreamError`` when GitHub cannot be reached.
        """
        owner, repo, number = parse_github_url(url)
        if number is None:
            raise ValueError("Expected an issue URL: https://github.com/<owner>/<repo>/issues/<number>")

        key = ("issue", owner.lower(), repo.lower(), number)
        try:
            card = await self._issue_cache.get_or_create(key, lambda: self._fetch_issue_card(owner, repo, number))
        except IssueNotFoundError:
            raise IssueNotFoundError(f"GitHub has no issue at https://github.com/{owner}/{repo}/issues/{number}.") from None
        return card.model_copy(deep=True)

    async def _fetch_issue_card(self, owner: str, repo: str, number: int) -> IssueCard:
        base = f"/repos/{owner}/{repo}"
        issue, repo_info = await asyncio.gather(
            self._github.get_json(f"{base}/issues/{number}"), self._github.get_json(base)
        )
        if "pull_request" in issue:
            raise ValueError("That link is a pull request, not an issue. Use an issue link.")

        total_comments = int(issue.get("comments") or 0)
        requests: List[Awaitable[Any]] = [self._github.get_json(f"{base}/community/profile")]
        if total_comments:
            last_page = math.ceil(total_comments / COMMENT_PAGE_SIZE)
            requests.append(
                self._github.get_json(
                    f"{base}/issues/{number}/comments", {"per_page": COMMENT_PAGE_SIZE, "page": last_page}
                )
            )
        outcomes = await asyncio.gather(*requests, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, RateLimitError):
                raise outcome
            if isinstance(outcome, BaseException) and not isinstance(outcome, (UpstreamError, LookupError)):
                raise outcome

        profile = outcomes[0] if isinstance(outcomes[0], dict) else {}
        comments = outcomes[1] if total_comments and isinstance(outcomes[1], list) else []

        contributing = ((profile.get("files") or {}).get("contributing") or {}).get("html_url")
        recent = [c for c in comments if isinstance(c, dict)]
        if recent and recent[-1].get("created_at"):
            last_comment = recent[-1]["created_at"]
        else:
            last_comment = (issue.get("updated_at") if total_comments else issue.get("created_at")) or issue["created_at"]

        canonical_owner = (repo_info.get("owner") or {}).get("login") or owner
        canonical_repo = repo_info.get("name") or repo
        commenters = [(c.get("user") or {}).get("login") or "" for c in reversed(recent)]

        return _build_card(
            issue,
            owner=canonical_owner,
            repo=canonical_repo,
            language=repo_info.get("language") or "Unknown",
            last_comment_date=last_comment[:10],
            handles=_handles(issue, commenters),
            contributing_url=contributing or _contribute_url(canonical_owner, canonical_repo),
            # Archived repositories are read-only on GitHub, which is the same outcome as a locked thread.
            locked=bool(issue.get("locked")) or bool(repo_info.get("archived")),
        )


# Shared engine instance used by the route handlers.
engine = TinyFishEngine()


def get_engine() -> TinyFishEngine:
    return engine
