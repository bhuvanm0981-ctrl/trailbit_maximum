"""Judging an issue: difficulty, the contribution checklist, and the health check."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .utils import activity_from_days, days_since

# --------------------------------------------------------------------------- difficulty
# Maintainers often state the level outright: "difficulty: easy", "size/M", "effort: high". That wins over guesses.
_LEVEL_LABEL = re.compile(
    r"^(?:difficulty|effort|complexity|size|level)\s*[:/_ -]\s*"
    r"(trivial|xs|easy|low|small|s|beginner|medium|moderate|m|hard|high|large|l|xl|expert|complex)$",
    re.I,
)
_LEVELS = {
    "trivial": 1, "xs": 1,
    "easy": 2, "low": 2, "small": 2, "s": 2, "beginner": 2,
    "medium": 3, "moderate": 3, "m": 3,
    "hard": 4, "high": 4, "large": 4, "l": 4,
    "xl": 5, "expert": 5, "complex": 5,
}
_EASIER_LABELS = {"documentation", "docs", "typo", "easy", "trivial", "beginner", "first-timers-only", "good-first-issue-docs"}
_HARDER_LABELS = {
    "hard", "advanced", "complex", "needs design", "breaking change", "breaking", "security", "performance",
    "concurrency", "infrastructure", "ci", "build", "devops", "refactor", "refactoring", "rfc",
}
_FEATURE_LABELS = {"enhancement", "feature", "feature request", "new feature"}


def estimate_difficulty(labels: Sequence[str], comment_count: int, body_length: int) -> int:
    """A rough 1-5 difficulty guess: an explicit level label if there is one, otherwise labels, discussion and length."""
    for label in labels:
        match = _LEVEL_LABEL.match(label.strip())
        if match:
            return _LEVELS[match.group(1).lower()]

    names = {label.lower() for label in labels}
    score = 2
    if names & _EASIER_LABELS:
        score -= 1
    if names & _HARDER_LABELS:
        score += 1
    if names & _FEATURE_LABELS:
        score += 1  # new behaviour needs more design than a fix does
    if comment_count >= 8:
        score += 1
    if body_length > 2500:
        score += 1
    return max(1, min(5, score))


# --------------------------------------------------------------------------- checklist
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


CHECKLIST_LENGTH = len(build_checklist("owner", "repo", 1, ""))


# --------------------------------------------------------------------------- health
def evaluate_health(
    status_metrics: Dict[str, Any],
    *,
    assignee_count: int = 0,
    state: str = "open",
    linked_prs: int = 0,
    claimed_by: Sequence[str] = (),
) -> Tuple[str, int, List[Dict[str, str]]]:
    """Derive ``(health_state, score, badges)`` for an issue.

    Activity is recomputed from ``last_comment_date`` rather than trusting the stored indicator.
    Locked and closed issues are blocked. Slow or stale threads, an assignee, an open pull request
    that mentions the issue, or someone saying they are on it all make it a caution.
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

    score = {"active": 100, "slow": 80, "stale": 55}[activity]
    if assignee_count > 0:
        score -= 20
        badges.append({"label": f"Assigned ({assignee_count})", "state": "warn", "detail": "Someone is already assigned. Ask in the thread before you start."})
    if linked_prs > 0:
        score -= 25
        badges.append(
            {
                "label": f"Open pull request ({linked_prs})",
                "state": "warn",
                "detail": "An open pull request mentions this issue. Read it to see whether it already fixes the problem.",
            }
        )
    if claimed_by:
        score -= 15
        names = ", ".join(f"@{name}" for name in claimed_by[:3])
        badges.append({"label": "Claimed in comments", "state": "warn", "detail": f"{names} said they are working on it. Ask before you start."})

    if locked or closed:
        score = min(score, 10)
        health_state = "blocked"
    elif score >= 90:
        health_state = "healthy"
    else:
        health_state = "caution"

    return health_state, max(0, score), badges
