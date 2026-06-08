"""Global live-trading toggle — Condition 2 of the two-layer activation model.

State lives in ``system_settings`` (key ``global_live_trading_enabled``) and is
read on the hot path by the execution router immediately before it would route
a real order to the CLOB. Reads are cached in-process for
``CACHE_TTL_SECONDS`` so a busy execute() loop does not slam the DB on every
candidate.

This module mirrors ``domain/ops/kill_switch.py`` deliberately: the same tiny
TTL cache, the same ``_fetch_flag`` truthy-parse, the same single asyncio.Lock
coalescing cold-cache reads. The ONE behavioral difference is the fail
direction: the kill switch fails SAFE by returning *True* (assume halted) on a
DB blip, whereas the global live gate fails SAFE by returning *False* (assume
NOT live → route to paper). For live activation, "uncertain ⇒ paper" is the
only acceptable default.

This module never enables live by default. The seed migration
(091_live_trade_activation.sql) writes 'false', and a missing key or any read
error also resolves to False.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import asyncpg

from ...database import get_pool

logger = logging.getLogger(__name__)


CACHE_TTL_SECONDS: float = 30.0

_SETTING_KEY = "global_live_trading_enabled"
_TRUTHY = {"true", "1", "yes", "on"}


class _Cache:
    """Tiny TTL cache for the global live-trading flag.

    Holds (expires_at_monotonic, value). ``read`` returns ``None`` when the
    entry is missing or stale; the caller then re-fetches from DB and writes
    back via ``store``. A single ``asyncio.Lock`` keeps concurrent execute()
    evaluations from issuing parallel SELECTs on a cold cache — they coalesce
    on the lock and the second waiter sees a warm entry.
    """

    def __init__(self) -> None:
        self._expires: float = 0.0
        self._value: bool = False
        self._has_value: bool = False
        self._lock = asyncio.Lock()

    def read(self) -> Optional[bool]:
        if not self._has_value:
            return None
        if time.monotonic() >= self._expires:
            return None
        return self._value

    def store(self, value: bool) -> None:
        self._value = value
        self._expires = time.monotonic() + CACHE_TTL_SECONDS
        self._has_value = True

    def invalidate(self) -> None:
        self._has_value = False
        self._expires = 0.0

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock


_cache = _Cache()


def invalidate_cache() -> None:
    """Force the next ``is_global_live_enabled`` call to re-read from DB.

    Called from ``set_global_live`` and from the admin endpoint after a write so
    an operator action is reflected immediately on the process that handled it
    rather than after the 30s TTL.
    """
    _cache.invalidate()


async def _fetch_flag(conn: asyncpg.Connection, key: str) -> bool:
    row = await conn.fetchrow(
        "SELECT value FROM system_settings WHERE key=$1", key,
    )
    if row is None:
        return False
    raw = (row["value"] or "").strip().lower()
    return raw in _TRUTHY


async def is_global_live_enabled(
    conn: Optional[asyncpg.Connection] = None,
) -> bool:
    """Return True only when the operator has globally enabled live trading.

    Cached for ``CACHE_TTL_SECONDS``. Pass ``conn`` only when the caller is
    already inside a transaction it wants the read to share; the execution
    router passes ``None`` so it picks up a short-lived pooled connection.

    Fail-safe to PAPER: a missing key OR any DB error resolves to ``False`` so
    an outage can never silently flip the system into live trading.
    """
    cached = _cache.read()
    if cached is not None:
        return cached

    async with _cache.lock:
        cached = _cache.read()
        if cached is not None:
            return cached
        try:
            if conn is not None:
                value = await _fetch_flag(conn, _SETTING_KEY)
            else:
                pool = get_pool()
                async with pool.acquire() as c:
                    value = await _fetch_flag(c, _SETTING_KEY)
        except Exception as exc:
            # Fail SAFE toward paper: if we cannot read the flag we must NOT
            # assume live. Log loudly and let the next call try again. We do
            # not cache the failure, so the very next call re-attempts the read.
            logger.error("global_live_gate read failed: %s", exc)
            return False
        _cache.store(value)
        return value


async def set_global_live(
    enabled: bool,
    conn: Optional[asyncpg.Connection] = None,
) -> bool:
    """Upsert the global live-trading flag and invalidate the cache.

    Writes 'true'/'false' to ``system_settings`` and clears the TTL cache so
    the next read reflects the new state immediately. Returns the value just
    written. Callers that need an audit trail must write it themselves (the
    admin endpoint does this via ``write_mode_change_event``); this function
    only owns the flag + cache.
    """
    sql = (
        "INSERT INTO system_settings (key, value, updated_at) "
        "VALUES ($1, $2, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()"
    )
    value = "true" if enabled else "false"
    if conn is not None:
        await conn.execute(sql, _SETTING_KEY, value)
    else:
        pool = get_pool()
        async with pool.acquire() as c:
            await c.execute(sql, _SETTING_KEY, value)
    invalidate_cache()
    return enabled
