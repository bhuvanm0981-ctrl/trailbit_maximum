"""Bookmarks: each visitor saves issues to SQLite, lists their own, and removes them."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_max_bookmarks
from ..database import Bookmark, get_session
from ..models.request import ResearchRequest
from ..models.response import BookmarkConfirmation, BookmarkDeleted, BookmarkOut
from ..services.engine import TinyFishEngine, get_engine
from ..services.github import IssueNotFoundError
from ..visitor import get_visitor_id

router = APIRouter(tags=["bookmarks"])

# Column limits, so one oversized title cannot be written to the database.
_TITLE_MAX = 500
_URL_MAX = 500


@router.post("/bookmarks", response_model=BookmarkConfirmation, status_code=201)
async def add_bookmark(
    body: ResearchRequest,
    response: Response,
    owner: str = Depends(get_visitor_id),
    session: AsyncSession = Depends(get_session),
    engine: TinyFishEngine = Depends(get_engine),
) -> BookmarkConfirmation:
    """Save an issue for this visitor.

    The browser sends only the issue's URL. The title, repository and link that get stored come from
    GitHub (through the engine's cache), never from the request, so nobody can store a link or text
    of their own choosing. Saving an issue that is already saved is a no-op that returns 200.
    """
    try:
        card = await engine.research_issue(body.github_url)
    except IssueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = await session.get(Bookmark, (owner, card.id))
    if existing is not None:
        response.status_code = 200
        return BookmarkConfirmation(created=False, bookmark=BookmarkOut.model_validate(existing))

    limit = get_max_bookmarks()
    count = await session.scalar(select(func.count()).select_from(Bookmark).where(Bookmark.owner_id == owner))
    if (count or 0) >= limit:
        raise HTTPException(status_code=409, detail=f"You can keep up to {limit} bookmarks. Remove one to save another.")

    bookmark = Bookmark(
        owner_id=owner,
        id=card.id,
        title=card.title[:_TITLE_MAX],
        repo_name=card.repo_name,
        repo_owner=card.repo_owner,
        programming_language=card.programming_language,
        github_issue_url=card.github_issue_url[:_URL_MAX],
    )
    session.add(bookmark)
    try:
        await session.commit()
    except IntegrityError:
        # A second request from the same visitor saved this issue between our check and our insert.
        await session.rollback()
        existing = await session.get(Bookmark, (owner, card.id))
        if existing is None:
            raise HTTPException(status_code=409, detail="Could not save this bookmark. Try again.") from None
        response.status_code = 200
        return BookmarkConfirmation(created=False, bookmark=BookmarkOut.model_validate(existing))

    await session.refresh(bookmark)
    return BookmarkConfirmation(created=True, bookmark=BookmarkOut.model_validate(bookmark))


@router.get("/bookmarks", response_model=List[BookmarkOut])
async def list_bookmarks(
    owner: str = Depends(get_visitor_id), session: AsyncSession = Depends(get_session)
) -> List[BookmarkOut]:
    """This visitor's saved issues, most recently saved first."""
    result = await session.execute(
        select(Bookmark).where(Bookmark.owner_id == owner).order_by(Bookmark.bookmarked_at.desc(), Bookmark.id)
    )
    return [BookmarkOut.model_validate(row) for row in result.scalars().all()]


@router.delete("/bookmarks/{issue_id}", response_model=BookmarkDeleted)
async def remove_bookmark(
    issue_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]{1,40}$", description="The GitHub issue id."),
    owner: str = Depends(get_visitor_id),
    session: AsyncSession = Depends(get_session),
) -> BookmarkDeleted:
    bookmark = await session.get(Bookmark, (owner, issue_id))
    if bookmark is None:
        raise HTTPException(status_code=404, detail="That issue is not bookmarked.")
    await session.delete(bookmark)
    await session.commit()
    return BookmarkDeleted(id=issue_id)
