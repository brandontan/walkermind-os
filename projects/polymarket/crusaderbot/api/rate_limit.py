"""Inbound HTTP rate limiting — public abuse control.

A lightweight, dependency-free sliding-window limiter applied as ASGI
middleware. It caps how many requests a single client (resolved by real
source IP behind the Fly proxy) may make within a rolling window, returning
``429 Too Many Requests`` with a ``Retry-After`` header once the ceiling is
exceeded.

Scope and intent:
  * Protects the public API + webhook surface from untrusted-user abuse.
  * Health/readiness probes and the Telegram webhook are exempt so platform
    health checks and update delivery are never throttled.
  * In-memory and per-process: the bot runs as a single Fly instance, so a
    shared store is unnecessary. The limiter is asyncio-only (no threading)
    and bounds its own memory by pruning idle clients.

Wiring (``main.py``)::

    from .api.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import get_settings

log = logging.getLogger("crusaderbot.ratelimit")

# Paths that must never be throttled. Health/readiness back the Fly platform
# health checks; the Telegram webhook carries update delivery and is already
# secret-gated, so throttling it would silently drop user messages.
_EXEMPT_PATHS: frozenset[str] = frozenset(
    {"/health", "/ready", "/api/web/health", "/telegram/webhook"}
)

# Hard ceiling on the number of distinct client keys tracked at once. When
# exceeded, the most idle clients are evicted so a spray of unique source IPs
# cannot grow the table without bound.
_MAX_TRACKED_CLIENTS = 10_000


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client sliding-window request limiter.

    Configured via ``Settings``: ``RATE_LIMIT_ENABLED`` (master switch),
    ``RATE_LIMIT_RPM`` (requests allowed per window) and
    ``RATE_LIMIT_WINDOW_SECONDS`` (window length). Disabled => pass-through.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        s = get_settings()
        self._enabled: bool = bool(s.RATE_LIMIT_ENABLED)
        self._limit: int = int(s.RATE_LIMIT_RPM)
        self._window: float = float(s.RATE_LIMIT_WINDOW_SECONDS)
        # client key -> monotonic timestamps of recent allowed requests
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _client_key(request: Request) -> str:
        """Resolve the real client IP behind the Fly edge proxy.

        Preference order: Fly's per-request client IP header, then the first
        hop of ``X-Forwarded-For``, then the direct socket peer. Falling back
        to a constant string would lump every anonymous caller together, so we
        only do so when no source can be determined at all.
        """
        fly_ip = request.headers.get("fly-client-ip")
        if fly_ip:
            return fly_ip.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    async def _check(self, key: str, now: float) -> tuple[bool, float]:
        """Record a hit and decide if the client is over the limit.

        Returns ``(allowed, retry_after_seconds)``. The window is rolling:
        timestamps older than ``now - window`` are discarded before counting.
        """
        cutoff = now - self._window
        async with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= _MAX_TRACKED_CLIENTS:
                    self._evict_idle(cutoff)
                bucket = deque()
                self._hits[key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self._limit:
                retry_after = self._window - (now - bucket[0])
                return False, max(retry_after, 1.0)

            bucket.append(now)
            return True, 0.0

    def _evict_idle(self, cutoff: float) -> None:
        """Drop clients whose newest hit is older than the window.

        Called under the lock when the table hits its cap. Bounds memory
        against a flood of unique source IPs.
        """
        stale = [k for k, b in self._hits.items() if not b or b[-1] <= cutoff]
        for k in stale:
            del self._hits[k]

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if (
            not self._enabled
            or path in _EXEMPT_PATHS
            or path.startswith("/legal/")
        ):
            return await call_next(request)

        key = self._client_key(request)
        allowed, retry_after = await self._check(key, time.monotonic())
        if not allowed:
            retry_secs = int(retry_after) + 1
            log.warning(
                "rate limit exceeded",
                extra={
                    "client": key,
                    "path": request.url.path,
                    "method": request.method,
                    "limit_rpm": self._limit,
                    "retry_after": retry_secs,
                },
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "retry_after": retry_secs,
                },
                headers={"Retry-After": str(retry_secs)},
            )
        return await call_next(request)
