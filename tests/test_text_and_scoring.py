"""Pure functions: URL parsing, text extraction, topics, claims, guide rules, difficulty, checklist and health."""

from datetime import timedelta

import pytest

from backend.scoring import CHECKLIST_LENGTH, build_checklist, estimate_difficulty, evaluate_health
from backend.text import clean_topics, contributing_highlights, extract_paths, find_claims, summarize_body
from backend.utils import activity_from_days, days_since, parse_github_url, split_query_values, today


def metrics(days_ago, locked=False):
    date = (today() - timedelta(days=days_ago)).isoformat()
    return {"is_locked": locked, "activity_indicator": activity_from_days(days_ago), "last_comment_date": date}


# ------------------------------------------------------------------ utils
@pytest.mark.parametrize("url,expected", [
    ("https://github.com/o/r/issues/12", ("o", "r", 12)),
    ("https://www.github.com/o/r/issues/12/", ("o", "r", 12)),
    ("https://github.com/o/r", ("o", "r", None)),
    ("https://github.com/o/r.git", ("o", "r", None)),
])
def test_parse_github_url(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize("url", ["", "   ", "http://github.com/o/r/issues/1", "https://evil.example/o/r/issues/1", "https://github.com/o/r/pull/1",
                                 "https://github.com/o/r/issues/0", "https://github.com/o/r/issues/abc", "https://github.com.evil.example/o/r/issues/1"])
def test_parse_github_url_rejects(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


def test_split_query_values():
    assert split_query_values(["Go,Rust", "go", " ", "Python"]) == ["Go", "Rust", "Python"]
    assert split_query_values(None) == []
    with pytest.raises(ValueError):
        split_query_values(["x" * 61])
    with pytest.raises(ValueError):
        split_query_values([str(i) for i in range(13)])


def test_activity_and_days():
    assert [activity_from_days(d) for d in (0, 14, 15, 60, 61)] == ["active", "active", "slow", "slow", "stale"]
    assert days_since("2000-01-01T00:00:00Z") > 9000
    assert days_since((today() + timedelta(days=5)).isoformat()) == 0  # never negative


# ------------------------------------------------------------------ text
def test_summarize_body():
    summary = summarize_body("## Title\nCall parse_dtstart() in `src/pkg/prreviews_observed.go`.\n> quoted **bold**\n<!-- hidden -->\n```py\nprint(1)\n```\n"
                             "See https://github.com/a/b/issues/442 and https://example.com/x [link](https://x.y).")
    assert "prreviews_observed.go" in summary and "parse_dtstart()" in summary  # underscores survive
    assert "a/b#442" in summary and "(link)" in summary
    assert not any(bad in summary for bad in ("`", "**", ">", "hidden", "print(1)", "https://"))
    assert summarize_body("") == summarize_body(None) == summarize_body("<!-- only -->")
    long = summarize_body("word " * 400)
    assert len(long) <= 481 and long.endswith("…")


def test_extract_paths():
    body = "see src/pkg/prreviews_observed.go, docs/a-b.md and https://x.io/a/b.html and 1/2.5 and a/b"
    assert extract_paths(body) == ["src/pkg/prreviews_observed.go", "docs/a-b.md"]
    assert len(extract_paths(" ".join(f"d/f{i}.py" for i in range(9)))) == 4


def test_clean_topics_drops_tracker_noise():
    labels = ["good first issue", "bug", "stage/040-covered-by-pr", "triage/accepted", "needs-kind", "agent/scanner", "help wanted",
              "area/ui", "123", "bug", "x" * 41, "testing"]
    assert clean_topics(labels) == ["bug", "area/ui", "testing"]
    assert len(clean_topics([f"topic{i}" for i in range(20)])) == 5


def comment(login, body, days_ago):
    return {"user": {"login": login}, "body": body, "created_at": (today() - timedelta(days=days_ago)).isoformat()}


def test_find_claims():
    comments = [
        comment("a", "I'd like to work on this", 5), comment("b", "Can I take this?", 3), comment("bot[bot]", "I'll fix this", 1),
        comment("c", "Looks good to me", 1), comment("old", "I'll work on it", 200), comment("a", "I'm working on it", 1),
    ]
    assert find_claims(comments) == ["a", "b"]  # not bots, not chatter, not stale claims, no repeats


GUIDE = """
# Contributing
This guide walks you through your first pull request.
Welcome! We love new contributors. Thanks for your interest in the project.
## Rules
- Run the full test suite with pytest before you open a pull request.
- Comment on the issue to claim it.
- All tests should pass (known bugs show as xfail).
- Keep each commit focused, and sign off your commits.
- See the documentation for more about testing.
- The weather is nice.
- Run the test suite to confirm everything works:
```
make test
```
"""


def test_contributing_highlights_keeps_rules_and_drops_introductions():
    rules = contributing_highlights(GUIDE, limit=10)
    assert "Run the full test suite with pytest before you open a pull request." in rules
    assert "Comment on the issue to claim it." in rules
    assert "All tests should pass (known bugs show as xfail)." in rules
    assert not any(r.endswith(":") for r in rules)  # a lead-in to a removed code block is not a rule
    assert not any("walks you through" in r or "Welcome" in r or "Thanks" in r or "weather" in r or r.startswith("See the") for r in rules)
    assert len(contributing_highlights(GUIDE, limit=2)) == 2
    assert contributing_highlights(None) == [] == contributing_highlights("")


# ------------------------------------------------------------------ scoring
@pytest.mark.parametrize("labels,comments,body,expected", [
    (["good first issue"], 0, 0, 2),
    (["documentation"], 0, 0, 1),
    (["performance"], 0, 0, 3),
    (["enhancement"], 0, 0, 3),
    (["performance", "enhancement"], 9, 3000, 5),
    (["documentation"], 0, 3000, 2),
    (["difficulty: hard"], 0, 0, 4),
    (["size/XS"], 20, 9999, 1),  # an explicit level label wins over every guess
    (["effort: medium"], 0, 0, 3),
    (["complexity/low"], 0, 0, 2),
])
def test_estimate_difficulty(labels, comments, body, expected):
    assert estimate_difficulty(labels, comments, body) == expected


def test_checklist():
    steps = build_checklist("acme", "pyparse", 11, "Python")
    assert len(steps) == CHECKLIST_LENGTH == 8
    assert [s["step_number"] for s in steps] == list(range(1, 9)) and not any(s["is_completed"] for s in steps)
    assert "acme/pyparse" in steps[1]["task"] and "fix-issue-11" in steps[4]["task"] and "Fixes #11" in steps[7]["task"] and "pytest" in steps[3]["task"]
    assert "go test" in build_checklist("a", "b", 1, "Go")[3]["task"]
    assert "README" in build_checklist("a", "b", 1, "COBOL")[3]["task"]


def test_health_healthy_and_each_penalty():
    assert evaluate_health(metrics(1))[:2] == ("healthy", 100)
    state, score, badges = evaluate_health(metrics(30))
    assert (state, score) == ("caution", 80) and badges[1]["label"] == "Slowing down"
    assert evaluate_health(metrics(90))[:2] == ("caution", 55)
    assert evaluate_health(metrics(1), assignee_count=2)[:2] == ("caution", 80)
    state, score, badges = evaluate_health(metrics(1), linked_prs=1)
    assert (state, score) == ("caution", 75) and any(b["label"] == "Open pull request (1)" for b in badges)
    state, score, badges = evaluate_health(metrics(1), claimed_by=["newbie"])
    assert (state, score) == ("caution", 85) and "@newbie" in badges[-1]["detail"]
    state, score, _ = evaluate_health(metrics(1), assignee_count=1, linked_prs=1, claimed_by=["x"])
    assert (state, score) == ("caution", 40)
    assert evaluate_health(metrics(500), assignee_count=3, linked_prs=3, claimed_by=["x"])[1] >= 0  # never negative


def test_health_blocked_states():
    state, score, badges = evaluate_health(metrics(1, locked=True))
    assert (state, score, badges[0]["label"]) == ("blocked", 10, "Locked")
    state, score, badges = evaluate_health(metrics(1), state="closed")
    assert (state, score, badges[0]["label"]) == ("blocked", 10, "Closed")
