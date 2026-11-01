"""Bookmarks: save issues to SQLite, list them, remove them."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import Bookmark, get_session
from ..models.response import BookmarkConfirmation, BookmarkDeleted, BookmarkOut, IssueCard

router = APIRouter(tags=["bookmarks"])

# Column limits, so one oversized title cannot be written to the database.
_TITLE_MAX = 500
_URL_MAX = 500


@router.post("/bookmarks", response_model=BookmarkConfirmation, status_code=201)
async def add_bookmark(
    card: IssueCard, response: Response, session: AsyncSession = Depends(get_session)
) -> BookmarkConfirmation:
    """Save an issue. Saving one that is already saved is a no-op that returns 200."""
    existing = await session.get(Bookmark, card.id)
    if existing is not None:
        response.status_code = 200
        return BookmarkConfirmation(created=False, bookmark=BookmarkOut.model_validate(existing))

    bookmark = Bookmark(
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
        # A second request saved the same issue between our check and our insert.
        await session.rollback()
        existing = await session.get(Bookmark, card.id)
        if existing is None:
            raise HTTPException(status_code=409, detail="Could not save this bookmark. Try again.")
        response.status_code = 200
        return BookmarkConfirmation(created=False, bookmark=BookmarkOut.model_validate(existing))

    await session.refresh(bookmark)
    return BookmarkConfirmation(created=True, bookmark=BookmarkOut.model_validate(bookmark))


@router.get("/bookmarks", response_model=List[BookmarkOut])
async def list_bookmarks(session: AsyncSession = Depends(get_session)) -> List[BookmarkOut]:
    """Every saved issue, most recently saved first."""
    result = await session.execute(select(Bookmark).order_by(Bookmark.bookmarked_at.desc(), Bookmark.id))
    return [BookmarkOut.model_validate(row) for row in result.scalars().all()]


@router.delete("/bookmarks/{issue_id}", response_model=BookmarkDeleted)
async def remove_bookmark(
    issue_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]{1,40}$", description="The GitHub issue id."),
    session: AsyncSession = Depends(get_session),
) -> BookmarkDeleted:
    bookmark = await session.get(Bookmark, issue_id)
    if bookmark is None:
        raise HTTPException(status_code=404, detail="That issue is not bookmarked.")
    await session.delete(bookmark)
    await session.commit()
    return BookmarkDeleted(id=issue_id)
