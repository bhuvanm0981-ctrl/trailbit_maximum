"""Shared helpers for the Trailbit backend: URL parsing, query cleanup, text extraction, health scoring."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

# Activity thresholds, in days since the last comment.
ACTIVE_MAX_DAYS = 14
SLOW_MAX_DAYS = 60

_GITHUB_PATH = re.compile(
    r"^/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))"
    r"/(?P<repo>[A-Za-z0-9._-]{1,100})"
    r"(?:/issues/(?P<number>[1-9]\d{0,9}))?/?$"
)


# --------------------------------------------------------------------------- URLs and queries
def parse_github_url(url: str) -> Tuple[str, str, Optional[int]]:
    """Parse a GitHub repository or issue URL into ``(owner, repo, issue_number)``.

    ``issue_number`` is ``None`` for a bare repository URL.
    Raises ``ValueError`` for anything that is not an https GitHub repo/issue URL.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("A GitHub URL is required.")

    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or (parsed.netloc or "").lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Only https://github.com/... URLs are supported.")

    match = _GITHUB_PATH.match(parsed.path)
    if not match:
        raise ValueError(
            "Expected https://github.com/<owner>/<repo> or "
            "https://github.com/<owner>/<repo>/issues/<number>."
        )

    repo = match.group("repo")
    if repo.endswith(".git"):
        repo = repo[:-4]
    number = match.group("number")
    return match.group("owner"), repo, int(number) if number else None


def split_query_values(
    values: Optional[Iterable[str]], *, max_values: int = 12, max_length: int = 60
) -> List[str]:
    """Flatten repeated and comma-separated query values into a clean list.

    ``?language=Go&language=Rust`` and ``?language=Go,Rust`` both become
    ``["Go", "Rust"]``. Blank items are dropped and duplicates (ignoring case) removed.
    Raises ``ValueError`` when there are too many values or one is too long.
    """
    if not values:
        return []
    cleaned: List[str] = []
    seen = set()
    for raw in values:
        for part in str(raw).split(","):
            item = part.strip()
            if not item or item.lower() in seen:
                continue
            if len(item) > max_length:
                raise ValueError(f"Filter values may be at most {max_length} characters.")
            seen.add(item.lower())
            cleaned.append(item)
    if len(cleaned) > max_values:
        raise ValueError(f"At most {max_values} filter values are allowed per field.")
    return cleaned


# --------------------------------------------------------------------------- dates
def today() -> date:
    return datetime.now(timezone.utc).date()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def days_since(iso_date: str) -> int:
    """Whole days between an ISO ``YYYY-MM-DD`` date and today (never negative)."""
    return max(0, (today() - date.fromisoformat(iso_date[:10])).days)


def activity_from_days(days: int) -> str:
    """Map days-since-last-comment onto an activity indicator."""
    if days <= ACTIVE_MAX_DAYS:
        return "active"
    if days <= SLOW_MAX_DAYS:
        return "slow"
    return "stale"


# --------------------------------------------------------------------------- text extraction
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CODE_FENCE = re.compile(r"(```|~~~).*?\1", re.S)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")
_GITHUB_REF = re.compile(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)[^\s)]*")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
# Backticks, asterisks and blockquote markers only. Underscores stay, because they are part of
# identifiers such as prreviews_observed.go and only rarely mark emphasis in an issue body.
_INLINE_MARKS = re.compile(r"[`*]+|^\s{0,3}>+[ \t]?", re.M)
_PATH = re.compile(
    r"(?<![\w/.:@-])((?:[A-Za-z0-9_.@-]+/)+[A-Za-z0-9_-][A-Za-z0-9_.-]*\.[A-Za-z][A-Za-z0-9]{0,7})(?![\w/])"
)

NO_DESCRIPTION = "The author did not add a description. Read the discussion on GitHub before you start."


def summarize_body(body: Optional[str], limit: int = 480) -> str:
    """Plain-text summary of an issue body: markdown, HTML, code blocks and URLs removed."""
    text = body or ""
    for pattern, replacement in (
        (_HTML_COMMENT, " "),
        (_CODE_FENCE, " "),
        (_IMAGE, " "),
        (_GITHUB_REF, r"\1/\2#\3"),  # a link to another issue reads as owner/repo#123
        (_LINK, r"\1"),
        (_HTML_TAG, " "),
        (_URL, "(link)"),
        (_HEADING, ""),
        (_INLINE_MARKS, ""),
    ):
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return NO_DESCRIPTION
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:- ") + "…"


def extract_paths(body: Optional[str], limit: int = 4) -> List[str]:
    """File paths mentioned in an issue body, such as ``src/parser/mod.rs``."""
    text = _URL.sub(" ", body or "")
    found: List[str] = []
    for match in _PATH.finditer(text):
        path = match.group(1)
        if len(path) <= 80 and path not in found:
            found.append(path)
        if len(found) == limit:
            break
    return found


_EASIER_LABELS = {"documentation", "docs", "typo", "easy", "trivial", "beginner", "first-timers-only"}
_HARDER_LABELS = {"hard", "advanced", "complex", "needs design", "breaking change", "security", "performance", "difficulty: hard"}


def estimate_difficulty(labels: Sequence[str], comment_count: int, body_length: int) -> int:
    """A rough 1-5 difficulty guess from labels, discussion size and description length."""
    names = {label.lower() for label in labels}
    score = 2
    if names & _EASIER_LABELS:
        score -= 1
    if names & _HARDER_LABELS:
        score += 1
    if comment_count >= 8:
        score += 1
    if body_length > 2500:
        score += 1
    return max(1, min(5, score))


_TEST_STEP = {
    "Python": "Create a virtual environment, install the project's dependencies, and run `pytest`.",
    "JavaScript": "Run `npm install`, then `npm test` (check package.json for the exact scripts).",
    "TypeScript": "Run `npm install`, then `npm test` (check package.json for the exact scripts).",
    "Go": "Run `go build ./...` and `go test ./...` to confirm everything passes first.",
    "Rust": "Run `cargo build` and `cargo test` to confirm everything passes first.",
}


def build_checklist(owner: str, repo: str, number: int, language: str) -> List[Dict[str, Any]]:
    """The contribution steps for one issue, using its real repository, number and language."""
    tasks = [
        f"Read issue #{number} and its comments, then comment to say you would like to work on it.",
        f"Read the README and CONTRIBUTING guide of {owner}/{repo}, and check no open pull request already fixes this.",
        f"Fork {owner}/{repo} and clone your fork with `git clone https://github.com/<your-username>/{repo}.git`.",
        _TEST_STEP.get(language, "Follow the README to build the project and run its test suite."),
        f"Create a branch for your work with `git checkout -b fix-issue-{number}`.",
        "Make the smallest change that resolves the issue, and add or update a test that covers it.",
        "Run the tests and the project's linter or formatter, and fix anything they report.",
        f"Commit with a clear message, push your branch, and open a pull request that says `Fixes #{number}`.",
    ]
    return [{"step_number": i, "task": task, "is_completed": False} for i, task in enumerate(tasks, start=1)]


# --------------------------------------------------------------------------- health
def evaluate_health(
    status_metrics: Dict[str, Any], *, assignee_count: int = 0, state: str = "open"
) -> Tuple[str, int, List[Dict[str, str]]]:
    """Derive ``(health_state, score, badges)`` for an issue.

    Activity is recomputed from ``last_comment_date`` rather than trusting the stored
    indicator. Locked and closed issues are blocked; assigned or slow issues are cautions.
    """
    locked = bool(status_metrics["is_locked"])
    closed = state == "closed"
    days = days_since(status_metrics["last_comment_date"])
    activity = activity_from_days(days)

    badges: List[Dict[str, str]] = []
    if closed:
        badges.append({"label": "Closed", "state": "bad", "detail": "The issue is closed, so there is nothing left to pick up."})
    elif locked:
        badges.append({"label": "Locked", "state": "bad", "detail": "The conversation is locked or the repository is archived."})
    else:
        badges.append({"label": "Open for contributions", "state": "good", "detail": "The issue is open and the conversation is not locked."})

    activity_badges = {"active": ("Active", "good"), "slow": ("Slowing down", "warn"), "stale": ("Stale", "bad")}
    label, tone = activity_badges[activity]
    badges.append({"label": label, "state": tone, "detail": f"Last comment {days} day{'s' if days != 1 else ''} ago."})

    if assignee_count > 0:
        badges.append(
            {
                "label": f"Assigned ({assignee_count})",
                "state": "warn",
                "detail": "Someone is already assigned. Ask in the thread before you start.",
            }
        )

    score = {"active": 100, "slow": 80, "stale": 55}[activity]
    if assignee_count > 0:
        score -= 20
    if locked or closed:
        score = min(score, 10)
        health_state = "blocked"
    elif score >= 90:
        health_state = "healthy"
    else:
        health_state = "caution"

    return health_state, max(0, score), badges
