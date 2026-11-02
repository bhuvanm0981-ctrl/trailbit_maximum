"""GET STARTED: the contribution checklist for an issue, and the repository's own rules."""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models.request import ISSUE_URL_HINT, ResearchRequest
from ..models.response import ChecklistResponse, GuideResponse, PlanResponse
from ..scoring import build_checklist
from ..services.engine import TinyFishEngine, get_engine
from ..services.github import IssueNotFoundError
from ..utils import parse_github_url

router = APIRouter(tags=["plan"])

_LANGUAGE = re.compile(r"^[A-Za-z0-9+#. -]{0,30}$")


@router.post("/plan", response_model=PlanResponse)
async def contribution_plan(
    body: ResearchRequest, engine: TinyFishEngine = Depends(get_engine)
) -> PlanResponse:
    try:
        card = await engine.research_issue(body.github_url)
    except IssueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return PlanResponse(
        issue_id=card.id,
        title=card.title,
        repo_full_name=f"{card.repo_owner}/{card.repo_name}",
        github_issue_url=card.github_issue_url,
        contributing_guidelines_url=card.contributing_guidelines_url,
        context_summary=card.context_summary,
        actionable_checklist=card.actionable_checklist,
    )


@router.get("/checklist", response_model=ChecklistResponse)
async def checklist(
    github_url: str = Query(..., max_length=300),
    language: Optional[str] = Query(None, max_length=30),
) -> ChecklistResponse:
    """The steps for an issue, built from its URL and language alone. No GitHub call, so it is instant."""
    if language and not _LANGUAGE.match(language):
        raise HTTPException(status_code=422, detail="Unsupported language name.")
    try:
        owner, repo, number = parse_github_url(github_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=ISSUE_URL_HINT) from exc
    if number is None:
        raise HTTPException(status_code=422, detail=ISSUE_URL_HINT)
    return ChecklistResponse(repo_full_name=f"{owner}/{repo}", actionable_checklist=build_checklist(owner, repo, number, language or ""))


@router.post("/guide", response_model=GuideResponse)
async def guide(body: ResearchRequest, engine: TinyFishEngine = Depends(get_engine)) -> GuideResponse:
    """Rules quoted from the repository's CONTRIBUTING guide. Slower than the rest, so the page asks for it last."""
    try:
        highlights, source = await engine.guide_highlights(body.github_url)
    except IssueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GuideResponse(highlights=highlights, source_url=source)
