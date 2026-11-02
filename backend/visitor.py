"""Anonymous visitor identity: a random id in an httpOnly cookie. Bookmarks belong to it."""

from __future__ import annotations

import re
import secrets

from fastapi import Request, Response

COOKIE_NAME = "trailbit_vid"
COOKIE_MAX_AGE = 365 * 24 * 3600
_VALID = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def get_visitor_id(request: Request, response: Response) -> str:
    """The visitor's id from their cookie, or a fresh one that is set on the response.

    SameSite=Lax keeps other websites from sending this cookie with a cross-site POST or DELETE,
    and HttpOnly keeps page scripts from reading it.
    """
    current = request.cookies.get(COOKIE_NAME, "")
    if _VALID.match(current):
        return current
    visitor_id = secrets.token_urlsafe(24)
    response.set_cookie(
        COOKIE_NAME,
        visitor_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )
    return visitor_id
