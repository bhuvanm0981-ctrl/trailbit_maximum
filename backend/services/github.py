"""A small async client for the GitHub REST API, with plain-language errors."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("trailbit.github")

GITHUB_API = "https://api.github.com"


class IssueNotFoundError(LookupError):
    """GitHub has nothing at the requested address."""


class UpstreamError(Exception):
    """GitHub could not be reached or returned an error we cannot work around."""

    def __init__(self, message: str, *, status_code: int = 502, headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = headers or {}


class RateLimitError(UpstreamError):
    """GitHub's rate limit, or Trailbit's own budget for it, is used up."""

    def __init__(self, message: str, *, retry_after: int = 60) -> None:
        super().__init__(message, status_code=429, headers={"Retry-After": str(retry_after)})


class GitHubClient:
    """Adds the auth header, maps errors, remembers the quota, and falls back to anonymous if the token is rejected."""

    def __init__(self, token: Optional[str], client: Optional[httpx.AsyncClient] = None) -> None:
        self._token = (token or "").strip() or None
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        # Latest "x-ratelimit-*" numbers per resource ("core", "search"), shown by /ready.
        self.quota: Dict[str, Dict[str, int]] = {}

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "trailbit",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = await self._send(path, params)
        if response.status_code == 401 and self._token:
            logger.warning("GitHub rejected GITHUB_TOKEN; continuing without authentication.")
            self._token = None
            response = await self._send(path, params)
        self._remember_quota(response)
        return self._parse(response)

    async def _send(self, path: str, params: Optional[Dict[str, Any]]) -> httpx.Response:
        try:
            return await self._client.get(f"{GITHUB_API}{path}", params=params, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise UpstreamError("GitHub took too long to respond. Try again in a moment.", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach GitHub. Check your connection and try again.", status_code=502) from exc

    def _remember_quota(self, response: httpx.Response) -> None:
        resource = response.headers.get("x-ratelimit-resource")
        try:
            if resource:
                self.quota[resource] = {
                    "remaining": int(response.headers["x-ratelimit-remaining"]),
                    "limit": int(response.headers["x-ratelimit-limit"]),
                    "reset": int(response.headers["x-ratelimit-reset"]),
                }
        except (KeyError, ValueError):
            pass

    def _parse(self, response: httpx.Response) -> Any:
        code = response.status_code
        if code == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise UpstreamError("GitHub returned a response Trailbit could not read.") from exc
        if code in (404, 410):
            raise IssueNotFoundError("GitHub has nothing at that address.")

        message = _error_message(response)
        limited = (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in message.lower()
            or bool(response.headers.get("retry-after"))
        )
        if code in (403, 429) and limited:
            raise self._rate_limit_error(response)
        if code == 422:
            raise ValueError(f"GitHub could not run that search: {message}")
        raise UpstreamError(f"GitHub returned an error ({code}). Try again in a moment.")

    def _rate_limit_error(self, response: httpx.Response) -> RateLimitError:
        retry_after = 60
        when = ""
        reset = response.headers.get("x-ratelimit-reset", "")
        header_retry = response.headers.get("retry-after", "")
        if reset.isdigit():
            retry_after = int(reset) - int(time.time())
            when = f" (resets around {datetime.fromtimestamp(int(reset), tz=UTC):%H:%M} UTC)"
        elif header_retry.isdigit():
            retry_after = int(header_retry)
        retry_after = max(1, min(retry_after, 3600))
        hint = "" if self.authenticated else " Adding a GITHUB_TOKEN raises the limits a lot."
        return RateLimitError(f"GitHub's rate limit is used up for now{when}.{hint}", retry_after=retry_after)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            return body["message"]
    except ValueError:
        pass
    return response.reason_phrase or "unknown error"
