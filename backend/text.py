"""Turning raw GitHub text into card content: summaries, file paths, topics, claims and guide rules."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .utils import days_since

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


# --------------------------------------------------------------------------- topics
# Workflow labels maintainers use to run their tracker. They say nothing about what the issue is about.
_NOISE_PREFIX = re.compile(
    r"^(stage|triage|status|priority|resolution|lifecycle|workflow|state|needs?|waiting|blocked|stale|cla|dco|bot|agent|automation)([/:_ -]|$)",
    re.I,
)
_NOISE_EXACT = {"good first issue", "good-first-issue", "help wanted", "hacktoberfest", "duplicate", "invalid", "wontfix", "question"}


def clean_topics(labels: Iterable[str], limit: int = 5) -> List[str]:
    """Labels that describe the subject of an issue, without the tracker's own workflow labels."""
    topics: List[str] = []
    for label in labels:
        name = label.strip()
        if not name or len(name) > 40 or name.lower() in _NOISE_EXACT or _NOISE_PREFIX.match(name) or name.isdigit():
            continue
        if name not in topics:
            topics.append(name)
        if len(topics) == limit:
            break
    return topics


# --------------------------------------------------------------------------- claims
_CLAIM = re.compile(
    r"\b(?:i['’]?d like to (?:work|take|pick|try|tackle)|i['’]?ll (?:work|take|pick|do|handle|fix|try|tackle)|"
    r"i['’]?m (?:working|going to work|on it|taking|picking)|i am (?:working|going to work)|"
    r"can i (?:work|take|pick|have|try|be assigned)|may i (?:work|take)|working on (?:this|it)|"
    r"assign (?:this )?(?:to )?me|i will (?:work|take|fix|submit|pick)|i want to (?:work|take|fix))\b",
    re.I,
)
CLAIM_WINDOW_DAYS = 90


def find_claims(comments: Sequence[Dict[str, Any]], limit: int = 5) -> List[str]:
    """Logins of people who said, in a recent comment, that they are working on the issue."""
    claimed: List[str] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        login = (comment.get("user") or {}).get("login") or ""
        created = comment.get("created_at") or ""
        if not isinstance(login, str) or not isinstance(created, str) or not login or login.endswith("[bot]") or login in claimed or not created:
            continue
        try:
            recent = days_since(created) <= CLAIM_WINDOW_DAYS
        except ValueError:
            continue
        body = comment.get("body")
        if recent and isinstance(body, str) and _CLAIM.search(body):
            claimed.append(login)
        if len(claimed) == limit:
            break
    return claimed


# --------------------------------------------------------------------------- CONTRIBUTING guides
_RULE_WORDS = re.compile(
    r"\b(test|tests|pytest|lint|linter|format|formatter|style|commit|sign[- ]?off|cla|dco|branch|"
    r"pull request|pr|changelog|rebase|squash|discuss|assigned?|claim|before you|please (?:do|don't|read|make|run|add))\b",
    re.I,
)
# A rule tells the reader what to do: it either starts with an action or contains an obligation.
_IMPERATIVE = re.compile(
    r"^(?:please\s+)?(?:run|use|add|include|follow|write|keep|sign|squash|rebase|comment|remove|delete|update|open|submit|"
    r"create|fork|check|read|link|reference|name|make|ensure|do|don't|never|always|avoid|prefer|format|lint|test|commit|"
    r"push|describe|explain|wait|ask|discuss|assign|claim|document|rename|install|review|mention)\b",
    re.I,
)
_MODAL = re.compile(r"\b(?:must|should|need to|needs to|have to|required|make sure|please|do not|don't|never|always)\b", re.I)
# Introductions and navigation read like prose about the guide, not rules from it.
_FLUFF = re.compile(
    r"walks? you through|^(?:this|these|the following)\b.{0,60}\b(?:guide|document|page|section|file)\b|welcome|"
    r"thank(?:s| you)|we (?:love|appreciate|welcome)|table of contents|learn more|^see (?:the|our)\b",
    re.I,
)


def _guide_paragraphs(text: str) -> List[str]:
    cleaned = _CODE_FENCE.sub("\n\n", _HTML_COMMENT.sub(" ", text))
    # Guides are hard-wrapped, so rebuild paragraphs first: blank lines, headings and list items start a new one.
    paragraphs: List[str] = []
    current: List[str] = []
    for raw in cleaned.splitlines():
        stripped = raw.strip()
        starts_item = bool(re.match(r"(?:[-*+]|\d+[.)])\s+", stripped))
        if not stripped or stripped.startswith("#") or starts_item:
            if current:
                paragraphs.append(" ".join(current))
            current = [] if not stripped or stripped.startswith("#") else [stripped]
        else:
            current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def contributing_highlights(text: Optional[str], limit: int = 4, max_length: int = 190) -> List[str]:
    """Up to ``limit`` short rules lifted word-for-word from a CONTRIBUTING guide.

    Kept: sentences about tests, formatting, commits, branches and pull requests that tell the
    reader what to do. Dropped: headings, code, links, introductions and very short or long lines.
    """
    found: List[str] = []
    for paragraph in _guide_paragraphs(text or ""):
        paragraph = _LINK.sub(r"\1", _IMAGE.sub("", paragraph))
        paragraph = _HTML_TAG.sub(" ", paragraph)
        paragraph = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", paragraph)
        paragraph = re.sub(r"\s+", " ", _INLINE_MARKS.sub("", paragraph)).strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", paragraph):
            sentence = sentence.strip()
            # A sentence ending in a colon introduces a code block or list that was dropped, so on its own it says nothing.
            if not 30 <= len(sentence) <= max_length or sentence.endswith(":") or _URL.search(sentence) or _FLUFF.search(sentence):
                continue
            is_rule = _RULE_WORDS.search(sentence) and (_IMPERATIVE.match(sentence) or _MODAL.search(sentence))
            if is_rule and sentence not in found:
                found.append(sentence)
                if len(found) == limit:
                    return found
    return found
