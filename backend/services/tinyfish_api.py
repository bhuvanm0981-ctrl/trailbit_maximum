"""Async client for the TinyFish Search and Fetch APIs (https://docs.tinyfish.ai).

Both endpoints are free within daily limits and authenticate with an ``X-API-Key`` header.
TinyFish only enriches Trailbit: when ``TINYFISH_API_KEY`` is missing, or a call fails, the
callers carry on with GitHub data alone. Nothing here may break discovery or verification.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger("trailbit.tinyfish")

SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"


class TinyFishError(Exception):
    """A TinyFish call failed. Callers treat it as "no extra data", never as a user-facing error."""


class TinyFishClient:
    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.AsyncClient] = None) -> None:
        self._key = (os.getenv("TINYFISH_API_KEY", "") if api_key is None else api_key).strip()
        # The README's placeholder must not count as a key.
        if self._key.startswith("your_"):
            self._key = ""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self._key, "User-Agent": "trailbit"}

    async def search(
        self, query: str, *, include_domains: Optional[str] = None, purpose: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Ranked web results: dicts with ``title``, ``url`` and ``snippet``."""
        params: Dict[str, Any] = {"query": query}
        if include_domains:
            params["include_domains"] = include_domains
        if purpose:
            params["purpose"] = purpose
        data = await self._request("GET", SEARCH_URL, params=params)
        return [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("url")]

    async def fetch_text(
        self, url: str, *, include_selectors: Optional[Sequence[str]] = None, purpose: Optional[str] = None
    ) -> str:
        """The page at ``url`` as clean markdown. Raises ``TinyFishError`` if it could not be read."""
        body: Dict[str, Any] = {"urls": [url], "format": "markdown"}
        if include_selectors:
            body["include_selectors"] = list(include_selectors)
        if purpose:
            body["purpose"] = purpose
        data = await self._request("POST", FETCH_URL, json=body, timeout=45.0)
        for page in data.get("results") or []:
            text = page.get("text") if isinstance(page, dict) else None
            if isinstance(text, str) and text.strip():
                return text
        errors = data.get("errors") or []
        reason = errors[0].get("error") if errors and isinstance(errors[0], dict) else "empty page"
        raise TinyFishError(f"TinyFish could not read {url}: {reason}")

    async def _request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        if not self.configured:
            raise TinyFishError("TINYFISH_API_KEY is not set.")
        try:
            response = await self._client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise TinyFishError(f"Could not reach TinyFish: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise TinyFishError(f"TinyFish returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise TinyFishError("TinyFish returned a response Trailbit could not read.") from exc
        if not isinstance(data, dict):
            raise TinyFishError("TinyFish returned an unexpected response.")
        return data
