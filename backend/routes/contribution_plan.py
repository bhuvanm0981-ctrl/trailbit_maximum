"""GET STARTED: return the structured contribution checklist for an issue."""

from fastapi import APIRouter, Depends, HTTPException

from ..models.request import ResearchRequest
from ..models.response import PlanResponse
from ..services.tinyfish import IssueNotFoundError, TinyFishEngine, get_engine

router = APIRouter(tags=["plan"])


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
