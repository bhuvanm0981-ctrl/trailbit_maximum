"""DISCOVER: live "good first issue" search on GitHub, plus the options the page starts from."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..config import is_render
from ..models.response import FacetsResponse, IssueSummary
from ..services.engine import TinyFishEngine, get_engine
from ..utils import split_query_values

router = APIRouter(tags=["discover"])

MIN_QUERY_LENGTH = 2


@router.get("/issues", response_model=List[IssueSummary])
async def list_issues(
    response: Response,
    language: Optional[List[str]] = Query(
        None,
        description="One or more languages. Repeat the parameter or comma-separate: ?language=Go&language=Rust. "
        "Defaults to Python, JavaScript, TypeScript, Go and Rust.",
    ),
    topic: Optional[List[str]] = Query(
        None,
        description="One or more topics (any match) tested against labels, title and description: ?topic=cli,testing",
    ),
    q: Optional[str] = Query(None, max_length=100, description="Free-text search added to the GitHub query (2 or more characters)."),
    sort: str = Query("updated", pattern="^[a-z]{3,12}$", description="updated, newest, discussed or quiet."),
    page: int = Query(1, ge=1, le=10, description="1-based page of up to 30 issues. See the X-Has-More response header."),
    engine: TinyFishEngine = Depends(get_engine),
) -> List[IssueSummary]:
    try:
        languages = split_query_values(language, max_length=30)
        topics = split_query_values(topic)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    text = (q or "").strip()
    if text and len(text) < MIN_QUERY_LENGTH:
        raise HTTPException(status_code=422, detail=f"A search needs at least {MIN_QUERY_LENGTH} characters.")

    try:
        result = await engine.list_issues(language=languages, topic=topics, query=text or None, sort=sort, page=page)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    response.headers["X-Has-More"] = "true" if result.has_more else "false"
    # The checklist is the same eight steps for every card, so the list leaves it out; GET /api/checklist returns it.
    return [IssueSummary(**card.model_dump(exclude={"actionable_checklist"})) for card in result.cards]


@router.get("/facets", response_model=FacetsResponse)
async def facets(engine: TinyFishEngine = Depends(get_engine)) -> FacetsResponse:
    return FacetsResponse(**engine.facets(), show_token_hint=not engine.authenticated and not is_render())
