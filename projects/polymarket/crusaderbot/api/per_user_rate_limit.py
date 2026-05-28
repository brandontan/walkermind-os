"""Per-authenticated-user rate limiter for cost-sensitive WebTrader endpoints.

Complements ``api/rate_limit.py`` (per-source-IP global limit, 600/min by
default) with a tighter ceiling keyed on the authenticated user_id from
the JWT. The IP limiter still catches anonymous abuse; this dependency
catches a single authenticated user spamming withdrawal requests, copy
tasks, position close calls, or other operations that fan out to the
admin queue / exit watcher / on-chain submitter.

Usage from a FastAPI router:

    @router.post(
        "/wallet/withdraw",
        dependencies=[Depends(per_user_rate_limit("withdraw", limit=10))],
    )
    async def request_withdrawal(...): ...

The dependency runs after ``get_current_user``, so JWT validation
already happened and ``user["user_id"]`` is known. Buckets are
in-process — Fly runs the WebTrader as a single primary instance, so a
shared bucket across instances is not currently required. The bucket
table is capped at ``_MAX_TRACKED_KEYS`` and evicted idle-first when
the cap is exceeded, so a spray of distinct user_ids cannot grow it
without bound.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Annotated, Callable

from fastapi import Depends, HTTPException

from ..webtrader.backend.auth import get_current_user

# Hard ceiling on the number of (user_id, scope) buckets tracked in memory.
# At eviction time the oldest-last-hit buckets are dropped first.
_MAX_TRACKED_KEYS: int = 50_000

# Module-level state — single asyncio.Lock guards the dict.
_buckets: dict[tuple[str, str], deque[float]] = {}
_lock: asyncio.Lock = asyncio.Lock()


def per_user_rate_limit(
    scope: str,
    *,
    limit: int,
    window_seconds: float = 60.0,
) -> Callable[[Annotated[dict, Depends(get_current_user)]], object]:
    """Build a FastAPI dependency that enforces ``limit`` requests per
    ``window_seconds`` for the authenticated user under ``scope``.

    ``scope`` names the bucket — distinct scopes never share a budget,
    so a user's withdraw budget is independent of their copy-task budget.
    Use short, stable scope names (``"withdraw"``, ``"copy_task"``).

    The dependency raises ``HTTPException(429)`` with ``Retry-After``
    when the bucket overflows. Otherwise it returns ``None`` and the
    endpoint runs normally.
    """
    async def _enforce(
        user: Annotated[dict, Depends(get_current_user)],
    ) -> None:
        user_id = str(user.get("user_id") or "")
        if not user_id:
            # No authenticated user → defer to get_current_user's 401.
            return
        key = (user_id, scope)
        now = time.monotonic()
        cutoff = now - window_seconds
        async with _lock:
            bucket = _buckets.get(key)
            if bucket is None:
                if len(_buckets) >= _MAX_TRACKED_KEYS:
                    _evict_idle(cutoff)
                bucket = deque()
                _buckets[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = window_seconds - (now - bucket[0])
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"per-user rate limit ({limit}/{int(window_seconds)}s) "
                        f"exceeded for '{scope}'"
                    ),
                    headers={"Retry-After": str(max(int(retry_after) + 1, 1))},
                )
            bucket.append(now)

    return _enforce


def _evict_idle(cutoff: float) -> None:
    """Drop buckets whose newest hit is older than the window.

    Called under ``_lock`` when ``_buckets`` hits its cap. Bounds memory
    against a flood of distinct user_ids (e.g. token-stuffing attempts).
    """
    stale_keys = [
        k for k, bucket in _buckets.items()
        if not bucket or bucket[-1] <= cutoff
    ]
    for k in stale_keys:
        del _buckets[k]


def _clear_buckets_for_tests() -> None:
    """Test-only helper: drop every tracked bucket."""
    _buckets.clear()
