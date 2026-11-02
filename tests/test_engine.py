"""The research engine against the fake GitHub: discovery, one issue, errors, and the repository's guide."""

import asyncio

import httpx
import pytest
from conftest import tinyfish_returning

from backend.services.engine import MAX_PAGE, TinyFishEngine
from backend.services.github import IssueNotFoundError, RateLimitError, UpstreamError
from backend.services.tinyfish_api import TinyFishClient

pytestmark = pytest.mark.anyio
LANGS = ("python", "javascript", "typescript", "go", "rust")


def ids(page):
    return [card.id for card in page.cards]


# ------------------------------------------------------------------ discovery
async def test_default_page_searches_every_language_once(make_engine, fake):
    page = await make_engine().list_issues()
    assert fake.calls["/search/issues"] == 5
    assert ids(page) == ["3001", "1001", "2001", "1002", "4001"]  # newest activity first
    assert {c.programming_language for c in page.cards} == {"Python", "JavaScript", "TypeScript", "Go"}
    first = fake.requests[0].url.params
    assert all(part in first["q"] for part in ('label:"good first issue"', "is:issue", "is:open", "archived:false"))
    assert (first["sort"], first["order"], first["page"]) == ("updated", "desc", "1")
    assert fake.requests[0].headers["user-agent"] == "trailbit" and "authorization" not in fake.requests[0].headers


async def test_cards_are_mapped_from_the_search_results(make_engine):
    cards = {c.id: c for c in (await make_engine().list_issues()).cards}
    python = cards["1001"]
    assert python.topics == ["bug", "testing"]  # "good first issue" and workflow labels dropped
    assert python.affected_paths == ["src/pyparse/ics.py", "tests/test_ics.py"] and python.active_handles == ["author1"]
    assert (python.comment_count, python.assignee_count, python.state) == (4, 0, "open")
    assert python.opened_date and len(python.actionable_checklist) == 8 and "Fixes #11" in python.actionable_checklist[-1]["task"]
    assert cards["4001"].status_metrics["is_locked"] and cards["4001"].status_metrics["activity_indicator"] == "stale"
    assert cards["1002"].assignee_count == 1 and cards["1002"].difficulty_rating == 1 and cards["3001"].difficulty_rating == 5
    assert python.linked_prs == [] and python.claimed_by == []  # only the live check knows these


async def test_languages_text_sort_and_page_reach_github(make_engine, fake):
    engine = make_engine()
    page = await engine.list_issues(language=["go", "Rust"], query="  cancel   context ", sort="discussed", page=2)
    assert fake.calls["/search/issues"] == 2 and page.cards == [] and not page.has_more
    q = fake.requests[0].url.params
    assert 'language:"go"' in q["q"] and q["q"].endswith("cancel context") and (q["sort"], q["order"], q["page"]) == ("comments", "desc", "2")
    assert (await engine.list_issues(language="python", sort="quiet")).cards[0].id == "1002"  # fewest comments first
    assert fake.requests[-1].url.params["order"] == "asc"
    assert ids(await engine.list_issues(language=["python", "typescript"], sort="newest"))[0] == "1001"  # opened 9 days ago; the others 20
    assert (await engine.list_issues(language="rust")).cards == []


async def test_has_more_is_true_only_when_a_page_comes_back_full(make_engine, fake):
    fake.search["go"] = [fake.search["go"][0]] * 30
    engine = make_engine()
    page = await engine.list_issues(language="go")
    assert len(page.cards) == 30 and page.has_more
    assert not (await engine.list_issues(language="python")).has_more
    assert not (await engine.list_issues(language="go", page=MAX_PAGE)).has_more  # GitHub stops at 1,000 results


async def test_topic_filter_matches_any_topic_in_labels_title_or_body(make_engine, fake):
    engine = make_engine()
    assert ids(await engine.list_issues(topic=["testing", "accessibility"])) == ["1001", "2001"]  # newest activity first
    assert all(r.url.params["per_page"] == "30" for r in fake.requests)
    assert (await engine.list_issues(language="python", topic="nothing-matches")).cards == []


@pytest.mark.parametrize("kwargs", [{"sort": "random"}, {"page": 0}, {"page": 11}, {"language": 'C"; DROP'}])
async def test_bad_arguments_are_value_errors(make_engine, kwargs):
    with pytest.raises(ValueError):
        await make_engine().list_issues(**kwargs)


async def test_identical_searches_are_served_from_cache(make_engine, fake):
    engine = make_engine()
    await engine.list_issues()
    await engine.list_issues()
    assert fake.calls["/search/issues"] == 5
    await engine.list_issues(query="other words")
    assert fake.calls["/search/issues"] == 10


async def test_search_budget_protects_the_quota_and_stale_results_survive(make_engine, fake):
    engine = make_engine(search_budget=1)
    assert ids(await engine.list_issues(language="go")) == ["4001"]
    with pytest.raises(RateLimitError, match="as fast as its limit allows") as error:
        await engine.list_issues(language="python")  # a second distinct search in the same minute
    assert error.value.status_code == 429 and int(error.value.headers["Retry-After"]) >= 1
    assert fake.calls["/search/issues"] == 1  # the budget stopped it before GitHub was asked


async def test_an_expired_search_is_served_stale_when_github_fails(make_engine, fake):
    engine = make_engine(search_ttl=0.0)  # every result is immediately "expired"
    assert ids(await engine.list_issues(language="go")) == ["4001"]
    fake.search_rate_limited = True
    assert ids(await engine.list_issues(language="go")) == ["4001"]  # GitHub is rate limiting us; the page still works
    with pytest.raises(RateLimitError):
        await engine.list_issues(language="python")  # nothing stored for this one, so the error is real


# ------------------------------------------------------------------ github errors
async def test_rate_limit_error_names_the_reset_time_and_suggests_a_token(make_engine, fake):
    fake.search_rate_limited = True
    with pytest.raises(RateLimitError) as error:
        await make_engine().list_issues(language="go")
    assert "UTC" in str(error.value) and "GITHUB_TOKEN" in str(error.value) and 100 <= int(error.value.headers["Retry-After"]) <= 121


async def test_rejected_token_falls_back_to_anonymous(make_engine, fake):
    fake.reject_token = True
    engine = make_engine(token="ghp_bad")
    assert engine.authenticated
    assert ids(await engine.list_issues(language="go")) == ["4001"]
    assert not engine.authenticated and fake.calls["/search/issues"] == 2


async def test_a_good_token_is_sent_as_bearer(make_engine, fake):
    engine = make_engine(token="ghp_good")
    await engine.list_issues(language="go")
    assert fake.requests[0].headers["authorization"] == "Bearer ghp_good" and engine.authenticated


async def test_network_failure_and_timeout_become_upstream_errors(make_engine, fake):
    fake.down = True
    with pytest.raises(UpstreamError, match="Could not reach GitHub") as down:
        await make_engine().list_issues(language="go")
    assert down.value.status_code == 502

    def slow(request):
        raise httpx.ReadTimeout("slow")

    engine = TinyFishEngine(token="", client=httpx.AsyncClient(transport=httpx.MockTransport(slow)), tinyfish=TinyFishClient(api_key=""))
    with pytest.raises(UpstreamError) as timeout:
        await engine.research_issue("https://github.com/acme/pyparse/issues/11")
    assert timeout.value.status_code == 504


async def test_quota_is_remembered_from_response_headers(make_engine):
    engine = make_engine()
    await engine.list_issues(language="go")
    await engine.research_issue("https://github.com/acme/pyparse/issues/11")
    assert engine.quota()["search"]["remaining"] == 9 and engine.quota()["core"]["limit"] == 60


# ------------------------------------------------------------------ one issue
URL = "https://github.com/acme/pyparse/issues/{}".format


async def test_research_maps_the_live_issue(make_engine, fake):
    card = await make_engine().research_issue(URL(11))
    assert (card.id, card.programming_language, card.repo_owner, card.state) == ("1001", "Python", "acme", "open")
    assert card.contributing_guidelines_url.endswith(".github/CONTRIBUTING.md")
    assert card.active_handles[0] == "author1" and {"user3", "user2"} <= set(card.active_handles)  # the author, then the newest commenters
    assert card.status_metrics["activity_indicator"] == "active"
    assert card.comment_count == 4 and card.linked_prs == [] and card.claimed_by == []


async def test_last_comment_date_comes_from_the_newest_comment(make_engine, fake):
    from datetime import timedelta

    from backend.utils import today

    card = await make_engine().research_issue(URL(11))
    assert card.status_metrics["last_comment_date"] == (today() - timedelta(days=1)).isoformat()
    quiet = await make_engine().research_issue(URL(15))
    assert quiet.status_metrics["last_comment_date"] == (today() - timedelta(days=5)).isoformat()  # no comments: the day it was opened


async def test_long_threads_read_the_last_page_and_the_one_before_when_it_is_short(make_engine, fake):
    await make_engine().research_issue(URL(17))  # 61 comments: page 3 holds one comment, so page 2 is read too
    pages = [r.url.params["page"] for r in fake.requests if r.url.path.endswith("/17/comments")]
    assert pages == ["3", "2"]
    fake.requests.clear()
    await make_engine().research_issue(URL(18))  # 70 comments: page 3 holds ten, enough on its own
    assert [r.url.params["page"] for r in fake.requests if r.url.path.endswith("/18/comments")] == ["3"]


async def test_open_pull_requests_and_claims_are_detected(make_engine):
    card = await make_engine().research_issue(URL(16))
    assert card.linked_prs == ["https://github.com/acme/pyparse/pull/99"]  # not the closed PR, not a plain issue, not twice
    assert card.claimed_by == ["newbie"]  # not the bot, not the maintainer saying "go ahead"


async def test_an_old_claim_is_ignored(make_engine):
    assert (await make_engine().research_issue(URL(19))).claimed_by == []


async def test_closed_locked_and_archived_issues(make_engine):
    assert (await make_engine().research_issue(URL(13))).state == "closed"
    gopool = await make_engine().research_issue("https://github.com/umbrella/gopool/issues/41")
    assert gopool.status_metrics["is_locked"]
    assert gopool.contributing_guidelines_url == "https://github.com/umbrella/gopool/contribute"  # no community profile: the fallback link


async def test_archived_repository_counts_as_locked(make_engine, fake):
    fake.repos[("globex", "uikit")]["archived"] = True
    assert (await make_engine().research_issue("https://github.com/globex/uikit/issues/21")).status_metrics["is_locked"]


async def test_bad_targets(make_engine):
    engine = make_engine()
    with pytest.raises(ValueError, match="pull request"):
        await engine.research_issue(URL(14))
    with pytest.raises(IssueNotFoundError, match="issues/999"):
        await engine.research_issue(URL(999))
    for bad in ("https://github.com/acme/pyparse", "https://evil.example/a/b/issues/1", ""):
        with pytest.raises(ValueError):
            await engine.research_issue(bad)


async def test_concurrent_requests_share_one_set_of_github_calls(make_engine, fake):
    engine = make_engine()
    await asyncio.gather(*(engine.research_issue(URL(11)) for _ in range(4)))
    await engine.research_issue(URL(11))
    assert fake.calls["/repos/acme/pyparse/issues/11"] == 1 and fake.calls["/repos/acme/pyparse"] == 1


async def test_researched_cards_are_copies(make_engine):
    engine = make_engine()
    first = await engine.research_issue(URL(11))
    first.topics.append("tampered")
    assert "tampered" not in (await engine.research_issue(URL(11))).topics


async def test_a_stale_issue_is_served_when_github_goes_down(make_engine, fake):
    engine = make_engine(issue_ttl=0.0)
    assert (await engine.research_issue(URL(11))).id == "1001"
    fake.down = True
    assert (await engine.research_issue(URL(11))).id == "1001"


# ------------------------------------------------------------------ the repository's guide
GUIDE = "# Contributing\n- Run the full test suite with pytest before you open a pull request.\n- Comment on the issue to claim it.\n"


async def test_guide_highlights_quote_the_repositorys_rules(make_engine):
    tinyfish = tinyfish_returning(GUIDE)
    engine = make_engine(tinyfish=tinyfish)
    rules, source = await engine.guide_highlights(URL(11))
    assert rules == ["Run the full test suite with pytest before you open a pull request.", "Comment on the issue to claim it."]
    assert source.endswith("CONTRIBUTING.md") and len(tinyfish.calls) == 1
    await engine.guide_highlights(URL(11))
    assert len(tinyfish.calls) == 1  # cached


async def test_guide_is_empty_without_a_key_without_a_file_or_when_tinyfish_fails(make_engine):
    assert (await make_engine().guide_highlights(URL(11)))[0] == []  # no TinyFish key
    tinyfish = tinyfish_returning(GUIDE)
    assert (await make_engine(tinyfish=tinyfish).guide_highlights("https://github.com/umbrella/gopool/issues/41"))[0] == []
    assert tinyfish.calls == []  # no guide file, so TinyFish is never asked
    assert (await make_engine(tinyfish=tinyfish_returning(GUIDE, status=500)).guide_highlights(URL(11)))[0] == []
    with pytest.raises(IssueNotFoundError):
        await make_engine(tinyfish=tinyfish_returning(GUIDE)).guide_highlights(URL(999))
