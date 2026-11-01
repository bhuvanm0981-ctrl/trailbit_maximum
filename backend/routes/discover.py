"""DISCOVER: live "good first issue" search on GitHub, plus the filter options the UI offers."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models.response import FacetsResponse, IssueCard
from ..services.tinyfish import TinyFishEngine, get_engine
from ..utils import split_query_values

router = APIRouter(tags=["discover"])


@router.get("/issues", response_model=List[IssueCard])
async def list_issues(
    language: Optional[List[str]] = Query(
        None,
        description="One or more languages. Repeat the parameter or comma-separate: ?language=Go&language=Rust. "
        "Defaults to Python, JavaScript, TypeScript, Go and Rust.",
    ),
    topic: Optional[List[str]] = Query(
        None,
        description="One or more topics (any match) tested against labels, title and description: ?topic=cli,testing",
    ),
    q: Optional[str] = Query(None, max_length=100, description="Free-text search added to the GitHub query."),
    engine: TinyFishEngine = Depends(get_engine),
) -> List[IssueCard]:
    try:
        languages = split_query_values(language, max_length=30)
        topics = split_query_values(topic)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return await engine.list_issues(language=languages, topic=topics, query=q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/facets", response_model=FacetsResponse)
async def facets(engine: TinyFishEngine = Depends(get_engine)) -> FacetsResponse:
    return FacetsResponse(**engine.facets())
