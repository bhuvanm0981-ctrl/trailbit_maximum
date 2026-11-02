"""CHECK: verify the health of an issue, live from GitHub."""

from fastapi import APIRouter, Depends, HTTPException

from ..models.request import ResearchRequest
from ..models.response import HealthBadge, VerifyResponse
from ..scoring import evaluate_health
from ..services.engine import TinyFishEngine, get_engine
from ..services.github import IssueNotFoundError
from ..utils import utc_now_iso

router = APIRouter(tags=["verify"])


@router.post("/verify", response_model=VerifyResponse)
async def verify(
    body: ResearchRequest, engine: TinyFishEngine = Depends(get_engine)
) -> VerifyResponse:
    try:
        card = await engine.research_issue(body.github_url)
    except IssueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    health_state, score, badges = evaluate_health(
        card.status_metrics,
        assignee_count=card.assignee_count,
        state=card.state,
        linked_prs=len(card.linked_prs),
        claimed_by=card.claimed_by,
    )
    return VerifyResponse(
        github_url=body.github_url,
        issue_id=card.id,
        health_state=health_state,
        health_score=score,
        badges=[HealthBadge(**badge) for badge in badges],
        checked_at=utc_now_iso(),
        issue=card,
    )
