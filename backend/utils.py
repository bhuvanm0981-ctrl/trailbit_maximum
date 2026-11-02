"""Small shared helpers: GitHub URL parsing, query cleanup and dates."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlparse

# Activity thresholds, in days since the last comment.
ACTIVE_MAX_DAYS = 14
SLOW_MAX_DAYS = 60

_GITHUB_PATH = re.compile(
    r"^/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))"
    r"/(?P<repo>[A-Za-z0-9._-]{1,100})"
    r"(?:/issues/(?P<number>[1-9]\d{0,9}))?/?$"
)


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


def today() -> date:
    return datetime.now(UTC).date()


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def days_since(iso_date: str) -> int:
    """Whole days between an ISO ``YYYY-MM-DD`` date (or timestamp) and today, never negative."""
    return max(0, (today() - date.fromisoformat(iso_date[:10])).days)


def activity_from_days(days: int) -> str:
    """Map days-since-last-comment onto an activity indicator."""
    if days <= ACTIVE_MAX_DAYS:
        return "active"
    if days <= SLOW_MAX_DAYS:
        return "slow"
    return "stale"
