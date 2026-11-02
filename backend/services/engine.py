"""The research engine: GitHub is the source of truth, TinyFish optionally adds the repository's own rules.

Discovery uses the issue search API (``label:"good first issue"``). One issue is researched from the
issue, repository, comments, timeline and community-profile endpoints. Results are cached briefly, an
expired result is still served if GitHub fails, and identical in-flight requests are shared, because
the unauthenticated limits are small (10 searches a minute, 60 other requests an hour).
Set ``GITHUB_TOKEN`` in ``.env`` to raise them.

TinyFish (``TINYFISH_API_KEY``) adds one thing on top, and the app works without it: Fetch reads the
CONTRIBUTING guide so a plan can quote the repository's own rules.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from ..config import ROOT_DIR
from ..models.response import IssueCard
from ..scoring import CHECKLIST_LENGTH, build_checklist, estimate_difficulty
from ..text import clean_topics, contributing_highlights, extract_paths, find_claims, summarize_body
from ..utils import activity_from_days, days_since, parse_github_url
from .cache import SlidingBudget, TTLCache
from .github import GitHubClient, IssueNotFoundError, RateLimitError, UpstreamError
from .tinyfish_api import TinyFishClient, TinyFishError

load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger("trailbit.engine")

GOOD_FIRST_LABEL = "good first issue"
MAX_RESULTS = 30
MAX_PAGE = 10  # GitHub search only returns the first 1,000 results
COMMENT_PAGE_SIZE = 30
GUIDE_TIMEOUT = 10.0  # seconds to read a CONTRIBUTING guide before the plan goes without it

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
    "documentation", "testing", "bug", "cli", "api", "ui", "accessibility",
    "performance", "refactor", "security", "typing", "help wanted",
]

# sort name -> (GitHub sort field, order). The same names order the merged results of several searches.
SORTS: Dict[str, Tuple[str, str]] = {
    "updated": ("updated", "desc"),
    "newest": ("created", "desc"),
    "discussed": ("comments", "desc"),
    "quiet": ("comments", "asc"),
}
_MERGE_KEY: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "updated": lambda item: str(item.get("updated_at") or ""),
    "newest": lambda item: str(item.get("created_at") or ""),
    "discussed": lambda item: _to_int(item.get("comments")),
    "quiet": lambda item: -_to_int(item.get("comments")),
}

FilterValues = Optional[Union[str, Sequence[str]]]


class NotAnIssueError(ValueError):
    """The URL is a pull request, not an issue."""


# What GitHub sends is trusted to be shaped right, but not to be perfect: one odd result must not take the whole page down.
_UNREADABLE = (KeyError, TypeError, ValueError, AttributeError)


def _first_date(*candidates: Any) -> str:
    """The first candidate that is a real ISO date or timestamp, as YYYY-MM-DD. Raises KeyError if none is."""
    for value in candidates:
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10]).isoformat()
            except ValueError:
                continue
    raise KeyError("a date")


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass
class IssuePage:
    cards: List[IssueCard]
    has_more: bool


# --------------------------------------------------------------------------- helpers
def _as_list(values: FilterValues) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values] if values.strip() else []
    return [v for v in values if isinstance(v, str) and v.strip()]


def _label_names(issue: Dict[str, Any]) -> List[str]:
    return [str(label["name"]) for label in issue.get("labels") or [] if isinstance(label, dict) and label.get("name")]


def _handles(issue: Dict[str, Any], commenters: Sequence[str] = ()) -> List[str]:
    """Assignees, then the author, then recent commenters. Bots are skipped."""
    ordered: List[Any] = [a.get("login") for a in issue.get("assignees") or [] if isinstance(a, dict)]
    ordered.append((issue.get("user") or {}).get("login"))
    ordered.extend(commenters)
    seen: List[str] = []
    for login in ordered:
        login = login if isinstance(login, str) else ""
        if login and not login.endswith("[bot]") and login not in seen:
            seen.append(login)
    return seen[:5]


def _repo_from_api_url(repository_url: str) -> Tuple[str, str]:
    parts = [p for p in urlparse(repository_url).path.split("/") if p]
    if len(parts) < 3 or parts[0] != "repos":
        raise ValueError("a search result that does not name its repository")
    return parts[1], parts[2]


def _matches_topics(issue: Dict[str, Any], topics: Sequence[str]) -> bool:
    haystack = " ".join([str(issue.get("title") or ""), *_label_names(issue), str(issue.get("body") or "")[:2000]]).lower()
    return any(topic in haystack for topic in topics)


def _clean_query(query: Optional[str]) -> str:
    printable = "".join(ch for ch in (query or "") if ch.isprintable())
    return re.sub(r"\s+", " ", printable).strip()


def _open_pull_requests(timeline: Sequence[Dict[str, Any]]) -> List[str]:
    """Open pull requests that mention the issue, from the timeline's cross-reference events."""
    urls: List[str] = []
    for event in timeline:
        if not isinstance(event, dict) or event.get("event") != "cross-referenced":
            continue
        source = (event.get("source") or {}).get("issue") or {}
        if not isinstance(source, dict):
            continue
        url = source.get("html_url")
        # Only real GitHub links are kept: this URL becomes a link on the page.
        if source.get("pull_request") and source.get("state") == "open" and isinstance(url, str) and url.startswith("https://github.com/") and url not in urls:
            urls.append(url)
    return urls[:5]


def contribute_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}/contribute"


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
    linked_prs: Sequence[str] = (),
    claimed_by: Sequence[str] = (),
) -> IssueCard:
    if issue.get("id") is None:
        raise KeyError("id")
    number = int(issue["number"])
    labels = _label_names(issue)
    body = issue.get("body") if isinstance(issue.get("body"), str) else ""
    comment_count = int(issue.get("comments") or 0)
    assignees = [a for a in issue.get("assignees") or [] if isinstance(a, dict) and a.get("login")]
    language = language or "Unknown"

    return IssueCard(
        id=str(issue["id"]),
        title=(issue.get("title") or "").strip() or f"Issue #{number}",
        repo_name=repo,
        repo_owner=owner,
        programming_language=language,
        topics=clean_topics(labels),
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
        opened_date=(issue.get("created_at") or "")[:10],
        linked_prs=list(linked_prs),
        claimed_by=list(claimed_by),
    )


# --------------------------------------------------------------------------- engine
class TinyFishEngine:
    """Live research: discovery by GitHub search, one issue by URL, and a repository's contributing rules."""

    def __init__(
        self,
        token: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        search_ttl: float = 300.0,
        issue_ttl: float = 600.0,
        tinyfish: Optional[TinyFishClient] = None,
        search_budget: Optional[int] = None,
    ) -> None:
        self._github = GitHubClient(os.getenv("GITHUB_TOKEN", "") if token is None else token, client)
        self._tinyfish = tinyfish or TinyFishClient()
        # An expired search or issue is still served for a day if GitHub cannot be reached when it is refreshed.
        self._search_cache = TTLCache(search_ttl, stale_ttl=86400.0)
        self._issue_cache = TTLCache(issue_ttl, stale_ttl=86400.0)
        self._guide_cache = TTLCache(3600.0, stale_ttl=86400.0)
        # Stay under GitHub's search limit (10 a minute anonymous, 30 with a token) so one busy minute cannot lock everyone out.
        self._search_budget = SlidingBudget(search_budget if search_budget is not None else (25 if self._github.authenticated else 8))

    @property
    def authenticated(self) -> bool:
        return self._github.authenticated

    @property
    def tinyfish_enabled(self) -> bool:
        return self._tinyfish.configured

    def quota(self) -> Dict[str, Dict[str, int]]:
        return {name: dict(values) for name, values in self._github.quota.items()}

    async def aclose(self) -> None:
        await self._github.aclose()
        await self._tinyfish.aclose()

    def facets(self) -> Dict[str, Any]:
        return {
            "languages": list(SUPPORTED_LANGUAGES),
            "topics": list(TOPIC_SUGGESTIONS),
            "sorts": list(SORTS),
            "checklist_length": CHECKLIST_LENGTH,
            "github_authenticated": self.authenticated,
            "tinyfish_enabled": self.tinyfish_enabled,
        }

    # ---- discovery -------------------------------------------------------------------------
    async def list_issues(
        self,
        language: FilterValues = None,
        topic: FilterValues = None,
        query: Optional[str] = None,
        *,
        sort: str = "updated",
        page: int = 1,
    ) -> IssuePage:
        """One page of open "good first issue" issues from GitHub.

        One search runs per language (the search API does not report an issue's language, so the
        language is known from the query itself) and the results are merged in ``sort`` order.
        Topics are matched against labels, title and description.
        """
        if sort not in SORTS:
            raise ValueError(f"Unknown sort {sort!r}. Use one of: {', '.join(SORTS)}.")
        if not 1 <= page <= MAX_PAGE:
            raise ValueError(f"The page must be between 1 and {MAX_PAGE}.")

        languages = self._resolve_languages(language)
        topics = [t.strip().lower() for t in _as_list(topic)]
        text = _clean_query(query)
        per_page = 30 if topics else min(30, max(6, math.ceil(MAX_RESULTS / len(languages))))

        outcomes = await asyncio.gather(
            *(self._search(qualifier, text, per_page, sort, page) for _, qualifier in languages), return_exceptions=True
        )

        found: List[Tuple[str, Dict[str, Any]]] = []
        first_error: Optional[BaseException] = None
        has_more = False
        for (display, _), outcome in zip(languages, outcomes, strict=True):
            if isinstance(outcome, (UpstreamError, ValueError)):
                first_error = first_error or outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                found.extend((display, item) for item in outcome)
                has_more = has_more or (len(outcome) >= per_page and page < MAX_PAGE)
        if not found and first_error:
            raise first_error

        if topics:
            found = [(lang, item) for lang, item in found if _matches_topics(item, topics)]
        found.sort(key=lambda pair: _MERGE_KEY[sort](pair[1]), reverse=True)

        cards: List[IssueCard] = []
        for display, item in found[:MAX_RESULTS]:
            try:
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
                        contributing_url=contribute_url(owner, repo),
                        locked=bool(item.get("locked")),
                    )
                )
            except _UNREADABLE as exc:
                logger.warning("Skipped a search result Trailbit could not read (%s: %s).", type(exc).__name__, exc)
        return IssuePage(cards=cards, has_more=has_more)

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

    async def _search(self, qualifier: str, text: str, per_page: int, sort: str, page: int) -> List[Dict[str, Any]]:
        async def fetch() -> List[Dict[str, Any]]:
            wait = self._search_budget.try_acquire()
            if wait:
                seconds = math.ceil(wait)
                raise RateLimitError(f"Trailbit is searching GitHub as fast as its limit allows. Try again in {seconds} seconds.", retry_after=seconds)
            parts = [f'label:"{GOOD_FIRST_LABEL}"', "is:issue", "is:open", "archived:false", f'language:"{qualifier}"']
            if text:
                parts.append(text)
            field, order = SORTS[sort]
            data = await self._github.get_json(
                "/search/issues",
                {"q": " ".join(parts), "sort": field, "order": order, "per_page": per_page, "page": page},
            )
            return list(data.get("items") or [])

        return await self._search_cache.get_or_create(("search", qualifier, text.lower(), per_page, sort, page), fetch)

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

    async def _recent_comments(self, base: str, number: int, total: int) -> List[Dict[str, Any]]:
        """The newest comments, oldest first: the last page, plus the one before it when the last is short."""
        last_page = math.ceil(total / COMMENT_PAGE_SIZE)
        path = f"{base}/issues/{number}/comments"
        page = await self._github.get_json(path, {"per_page": COMMENT_PAGE_SIZE, "page": last_page})
        page = page if isinstance(page, list) else []
        if len(page) < 10 and last_page > 1:
            try:
                earlier = await self._github.get_json(path, {"per_page": COMMENT_PAGE_SIZE, "page": last_page - 1})
            except RateLimitError:
                raise
            except (UpstreamError, LookupError):
                earlier = []
            page = (earlier if isinstance(earlier, list) else []) + page
        return page

    async def _fetch_issue_card(self, owner: str, repo: str, number: int) -> IssueCard:
        try:
            return await self._read_issue(owner, repo, number)
        except NotAnIssueError:
            raise
        except _UNREADABLE as exc:
            logger.warning("Could not read issue %s/%s#%s from GitHub (%s: %s).", owner, repo, number, type(exc).__name__, exc)
            raise UpstreamError("GitHub returned this issue in a shape Trailbit could not read. Open it on GitHub instead.") from exc

    async def _read_issue(self, owner: str, repo: str, number: int) -> IssueCard:
        base = f"/repos/{owner}/{repo}"
        issue, repo_info = await asyncio.gather(
            self._github.get_json(f"{base}/issues/{number}"), self._github.get_json(base)
        )
        if "pull_request" in issue:
            raise NotAnIssueError("That link is a pull request, not an issue. Use an issue link.")

        total_comments = _to_int(issue.get("comments"))
        extras: Dict[str, Awaitable[Any]] = {
            "profile": self._github.get_json(f"{base}/community/profile"),
            "timeline": self._github.get_json(f"{base}/issues/{number}/timeline", {"per_page": 100}),
        }
        if total_comments:
            extras["comments"] = self._recent_comments(base, number, total_comments)
        outcomes = dict(zip(extras, await asyncio.gather(*extras.values(), return_exceptions=True), strict=True))
        for outcome in outcomes.values():
            if isinstance(outcome, RateLimitError):
                raise outcome
            if isinstance(outcome, BaseException) and not isinstance(outcome, (UpstreamError, LookupError)):
                raise outcome  # only "GitHub said no" is survivable; a real bug must not be hidden

        profile = outcomes["profile"] if isinstance(outcomes["profile"], dict) else {}
        timeline = outcomes["timeline"] if isinstance(outcomes["timeline"], list) else []
        comments = outcomes.get("comments")
        recent = [c for c in comments if isinstance(c, dict)] if isinstance(comments, list) else []

        contributing = ((profile.get("files") or {}).get("contributing") or {}).get("html_url")
        # The newest comment's date, else when the issue was last touched, else when it was opened.
        last_comment = _first_date(
            recent[-1].get("created_at") if recent else None,
            issue.get("updated_at") if total_comments else None,
            issue.get("created_at"),
            issue.get("updated_at"),
        )

        canonical_owner = (repo_info.get("owner") or {}).get("login") or owner
        canonical_repo = repo_info.get("name") or repo
        commenters = [(c.get("user") or {}).get("login") or "" for c in reversed(recent)]

        return _build_card(
            issue,
            owner=canonical_owner,
            repo=canonical_repo,
            language=repo_info.get("language") or "Unknown",
            last_comment_date=last_comment,
            handles=_handles(issue, commenters),
            contributing_url=contributing or contribute_url(canonical_owner, canonical_repo),
            # Archived repositories are read-only on GitHub, which is the same outcome as a locked thread.
            locked=bool(issue.get("locked")) or bool(repo_info.get("archived")),
            linked_prs=_open_pull_requests(timeline),
            claimed_by=find_claims(recent),
        )

    # ---- the repository's own rules ----------------------------------------------------------
    async def guide_highlights(self, url: str) -> Tuple[List[str], str]:
        """``(rules, source_url)`` from the repository's CONTRIBUTING guide, read with TinyFish Fetch.

        Empty when TinyFish is off, the repository has no guide file, or the page could not be read.
        Never raises for a TinyFish problem. GitHub errors from researching the issue still propagate.
        """
        card = await self.research_issue(url)
        source = card.contributing_guidelines_url
        if not self.tinyfish_enabled or source.endswith("/contribute"):  # /contribute is the fallback link, not a file
            return [], source

        async def read() -> List[str]:
            try:
                # GitHub renders the guide inside <article class="markdown-body">; scoping to it drops the site chrome.
                text = await self._tinyfish.fetch_text(
                    source,
                    include_selectors=["article.markdown-body"],
                    purpose="Find the rules a new contributor must follow before opening a pull request.",
                )
            except TinyFishError:
                # Plain-text guides have no markdown-body; read the whole page and let the filter pick the rules.
                text = await self._tinyfish.fetch_text(source)
            return contributing_highlights(text)

        try:
            return await asyncio.wait_for(self._guide_cache.get_or_create(("guide", source), read), GUIDE_TIMEOUT), source
        except (TimeoutError, TinyFishError) as exc:
            logger.info("CONTRIBUTING guide skipped for %s: %s", source, exc or type(exc).__name__)
            return [], source


# Shared engine instance used by the route handlers.
engine = TinyFishEngine()


def get_engine() -> TinyFishEngine:
    return engine
