"""ASGI middleware: request ids and logging, security and cache headers, body size limit, rate limiting."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
import uuid
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("uvicorn.error")

Clock = Callable[[], float]

# Everything the page loads comes from this origin: scripts, styles, fonts and images are all self-hosted.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
)
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]{6,64}$")


async def send_json_with(send: Send, status: int, detail: str, extra: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> None:
    body = json.dumps({"detail": detail, **(extra or {})}).encode()
    raw = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    raw += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


async def send_json(send: Send, status: int, detail: str, headers: Optional[Dict[str, str]] = None) -> None:
    await send_json_with(send, status, detail, None, headers)


def _report(exc: BaseException) -> None:
    """Hand an unexpected error to Sentry if it is installed and configured; otherwise do nothing."""
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except ImportError:
        pass


def cache_policy(path: str) -> str:
    if path.startswith("/api/"):
        return "public, max-age=300" if path == "/api/facets" else "no-store"
    if path in ("/health", "/ready"):
        return "no-store"
    if path.startswith("/fonts/"):
        return "public, max-age=2592000"
    if path.startswith("/img/"):
        return "public, max-age=604800"
    return "no-cache"  # HTML, CSS and JS: always revalidate (the ETag makes that a cheap 304)


class RequestContextMiddleware:
    """Outermost layer: gives every request an id, adds the security and cache headers, logs API calls."""

    def __init__(self, app: ASGIApp, clock: Clock = time.perf_counter) -> None:
        self.app = app
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = self.clock()
        headers = Headers(scope=scope)
        supplied = headers.get("x-request-id", "")
        request_id = supplied if _REQUEST_ID.match(supplied) else uuid.uuid4().hex[:12]
        scope.setdefault("state", {})["request_id"] = request_id
        path = scope["path"]
        https = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https" or scope.get("scheme") == "https"
        status = 0

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = request_id
                for name, value in SECURITY_HEADERS:
                    out.setdefault(name, value)
                if not path.startswith(DOC_PATHS):  # the interactive docs load their UI from a CDN
                    out.setdefault("Content-Security-Policy", CSP)
                if https:
                    out.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
                if "cache-control" not in out:
                    out["Cache-Control"] = cache_policy(path)
            await send(message)

        responded = False

        async def tracking_send(message: Message) -> None:
            nonlocal responded
            if message["type"] == "http.response.start":
                responded = True
            await send_with_headers(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            # Answer here rather than letting Starlette do it from outside, so the error response carries the
            # same request id and security headers as every other response.
            logger.error("Unhandled error [%s] on %s %s", request_id, scope["method"], path, exc_info=exc)
            _report(exc)
            if responded:
                raise
            await send_json_with(tracking_send, 500, "Something went wrong on our side. Try again in a moment.", {"request_id": request_id})
        finally:
            if path.startswith("/api/"):
                logger.info("%s %s -> %s in %dms [%s]", scope["method"], path, status or 500, (self.clock() - started) * 1000, request_id)


class BodyLimitMiddleware:
    """Refuses request bodies over ``max_bytes``, whether they announce a length or stream in chunks."""

    class _TooLarge(Exception):
        pass

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        message = f"The request is too large. The limit is {self.max_bytes} bytes."
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await send_json(send, 413, message)
            return

        received = 0
        responded = False

        async def limited_receive() -> Message:
            nonlocal received
            event = await receive()
            if event["type"] == "http.request":
                received += len(event.get("body", b""))
                if received > self.max_bytes:
                    raise self._TooLarge()
            return event

        async def tracking_send(event: Message) -> None:
            nonlocal responded
            if event["type"] == "http.response.start":
                responded = True
            await send(event)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except self._TooLarge:
            if not responded:
                await send_json(send, 413, message)


HEAVY_ROUTES = {("GET", "/api/issues"), ("POST", "/api/verify"), ("POST", "/api/plan"), ("POST", "/api/guide"), ("POST", "/api/bookmarks")}


class RateLimitMiddleware:
    """A sliding one-minute window per visitor, plus one across everybody. Only /api is limited.

    Routes that spend GitHub quota (HEAVY_ROUTES) get their own, smaller per-visitor allowance.
    """

    def __init__(
        self, app: ASGIApp, *, per_visitor: int, heavy_per_visitor: int, overall: int, trust_proxy: bool,
        window: float = 60.0, clock: Clock = time.monotonic,
    ) -> None:
        self.app = app
        self.limits = {"general": per_visitor, "heavy": heavy_per_visitor}
        self.overall = overall
        self.trust_proxy = trust_proxy
        self.window = window
        self.clock = clock
        self._hits: Dict[Tuple[str, str], Deque[float]] = {}

    def client_ip(self, scope: Scope) -> str:
        peer = (scope.get("client") or ("unknown", 0))[0]
        if self.trust_proxy:
            first = Headers(scope=scope).get("x-forwarded-for", "").split(",")[0].strip()
            try:
                return str(ipaddress.ip_address(first))
            except ValueError:
                pass
        return peer

    def _window_for(self, key: Tuple[str, str], now: float) -> Deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def _retry_after(self, hits: Deque[float], limit: int, now: float) -> float:
        return 0.0 if len(hits) < limit else max(1.0, hits[0] + self.window - now)

    def _forget_idle(self, now: float) -> None:
        if len(self._hits) < 5000:
            return
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - self.window]:
            del self._hits[key]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        now = self.clock()
        kind = "heavy" if (scope["method"], scope["path"]) in HEAVY_ROUTES else "general"
        visitor = self._window_for((self.client_ip(scope), kind), now)
        everyone = self._window_for(("*", "all"), now)
        wait = max(self._retry_after(visitor, self.limits[kind], now), self._retry_after(everyone, self.overall, now))
        if wait:
            seconds = int(wait) + (0 if wait == int(wait) else 1)
            await send_json(send, 429, f"Too many requests. Try again in {seconds} seconds.", {"Retry-After": str(seconds)})
            return
        visitor.append(now)
        everyone.append(now)
        self._forget_idle(now)
        await self.app(scope, receive, send)
