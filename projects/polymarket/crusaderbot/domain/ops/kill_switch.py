"""Operator kill switch — the single source of truth for trade halts.

State lives in ``system_settings`` (key ``kill_switch_active``,
``kill_switch_lock_mode``) and is read on the hot path by the risk gate
(step [1]). Reads are cached in-process for ``CACHE_TTL_SECONDS`` so a
busy gate does not slam the DB on every signal.

The cache is intentionally simple — a single asyncio.Lock around a
timestamp+value tuple. No Redis, no shared state. A 30-second propagation
window after the operator flips the switch is acceptable and explicitly
documented in the R12f task brief; ``invalidate()`` is called from
``set_active()`` so an operator action is reflected immediately on the
process that handled the command.

The history table (``kill_switch_history``) is append-only. Every
``set_active()`` writes one row. The general audit.log also receives a
matching ``kill_switch_*`` event via ``audit.write`` from the caller
(admin handler) — this module only owns the ops-plane history table.
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

ACTION_PAUSE = "pause"
ACTION_RESUME = "resume"
ACTION_LOCK = "lock"
_VALID_ACTIONS = {ACTION_PAUSE, ACTION_RESUME, ACTION_LOCK}


class _Cache:
    """Tiny TTL cache for the kill-switch flag.

    Holds (expires_at_monotonic, value). ``read`` returns ``None`` when
    the entry is missing or stale; the caller then re-fetches from DB
    and writes back via ``store``. A single ``asyncio.Lock`` keeps
    concurrent gate evaluations from issuing parallel SELECTs on a cold
    cache — they coalesce on the lock and the second waiter sees a warm
    entry.
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
    """Force the next ``is_active`` call to re-read from DB.

    Exposed for tests and for any caller that needs to bypass the TTL
    immediately after an operator-driven mutation that did not go
    through ``set_active`` (for example, a direct DB tweak from a
    migration or a CLI tool).
    """
    _cache.invalidate()


async def _fetch_flag(conn: asyncpg.Connection, key: str) -> bool:
    row = await conn.fetchrow(
        "SELECT value FROM system_settings WHERE key=$1", key,
    )
    if row is None:
        return False
    raw = (row["value"] or "").strip().lower()
    return raw in {"true", "1", "yes", "on"}


async def is_active(conn: Optional[asyncpg.Connection] = None) -> bool:
    """Return True when the operator has paused trading.

    Cached for ``CACHE_TTL_SECONDS``. Pass ``conn`` only when the caller
    is already inside a transaction it wants the read to share — risk
    gate step [1] passes ``None`` so it picks up a short-lived
    connection from the pool.
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
                value = await _fetch_flag(conn, "kill_switch_active")
            else:
                pool = get_pool()
                async with pool.acquire() as c:
                    value = await _fetch_flag(c, "kill_switch_active")
        except Exception as exc:
            # On a DB blip we fail SAFE: assume the switch is ACTIVE so
            # no new trades route, log loudly, and let the next call
            # try again. A risk gate that opens the floodgates because
            # the read failed would be the worst possible default.
            logger.error("kill_switch is_active read failed: %s", exc)
            return True
        _cache.store(value)
        return value


async def get_lock_mode(conn: Optional[asyncpg.Connection] = None) -> bool:
    """Return True when the kill switch is in lock-mode.

    Lock mode means a /killswitch resume alone will not bring auto-trade
    back online — every user has had ``users.auto_trade_on`` flipped to
    FALSE and must re-enable manually. ``set_active(False)`` does not
    clear lock mode; the operator must call that explicitly.
    """
    try:
        if conn is not None:
            return await _fetch_flag(conn, "kill_switch_lock_mode")
        pool = get_pool()
        async with pool.acquire() as c:
            return await _fetch_flag(c, "kill_switch_lock_mode")
    except Exception as exc:
        logger.error("kill_switch get_lock_mode read failed: %s", exc)
        return False


async def _upsert(conn: asyncpg.Connection, key: str, value: bool) -> None:
    await conn.execute(
        "INSERT INTO system_settings (key, value, updated_at) "
        "VALUES ($1, $2, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, "
        "updated_at=NOW()",
        key, "true" if value else "false",
    )


async def record_history(
    conn: asyncpg.Connection,
    *,
    action: str,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> None:
    """Append a row to ``kill_switch_history``.

    Validates ``action`` against the allowed set so a typo can never
    produce a bogus entry that would later confuse the audit reviewer.
    """
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid kill switch action: {action!r}")
    await conn.execute(
        "INSERT INTO kill_switch_history (action, actor_id, reason) "
        "VALUES ($1, $2, $3)",
        action, actor_id, reason,
    )


async def set_active(
    *,
    action: str,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
    deactivate_users: bool = False,
) -> dict:
    """Flip the operator kill switch and record history in one transaction.

    ``action`` must be one of ``pause`` / ``resume`` / ``lock``.

    * ``pause``  -> kill_switch_active=true, lock_mode unchanged.
    * ``resume`` -> kill_switch_active=false, lock_mode=false. Risk gate
                    re-opens. Users with ``auto_trade_on=true`` resume
                    on their next signal.
    * ``lock``   -> kill_switch_active=true, lock_mode=true, AND every
                    user's ``users.auto_trade_on`` is forced to false.
                    Resuming requires the operator to call /killswitch
                    resume AND each user must re-opt-in.

    Returns a small dict with the resulting state and (for ``lock``) the
    number of user rows touched, so the caller can shape its operator
    reply.
    """
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid kill switch action: {action!r}")

    pool = get_pool()
    users_disabled = 0
    new_active = False
    new_lock = False
    async with pool.acquire() as conn:
        async with conn.transaction():
            if action == ACTION_PAUSE:
                await _upsert(conn, "kill_switch_active", True)
            elif action == ACTION_RESUME:
                await _upsert(conn, "kill_switch_active", False)
                await _upsert(conn, "kill_switch_lock_mode", False)
            elif action == ACTION_LOCK:
                await _upsert(conn, "kill_switch_active", True)
                await _upsert(conn, "kill_switch_lock_mode", True)
                # Force every user out of auto-trade. The status field on
                # users is ``auto_trade_on`` (see migrations/001_init.sql).
                # We capture the affected count so the operator reply can
                # report exactly how many users were paused.
                users_disabled = int(await conn.fetchval(
                    "WITH affected AS ("
                    "  UPDATE users SET auto_trade_on=FALSE "
                    "  WHERE auto_trade_on=TRUE RETURNING 1"
                    ") SELECT COUNT(*) FROM affected"
                ) or 0)
                if deactivate_users and users_disabled == 0:
                    # Optional explicit-zero hint kept for symmetry with
                    # callers that want to log a no-op lock action.
                    logger.info(
                        "kill_switch lock: no users had auto_trade_on=true"
                    )
            await record_history(
                conn, action=action, actor_id=actor_id, reason=reason,
            )
            # Read both flags back inside the transaction so the returned
            # payload mirrors actual DB state. ``pause`` intentionally
            # leaves lock_mode untouched, so a pause on an already-locked
            # system must report lock_mode=true — computing the value
            # from ``action`` alone would mis-report the audit payload
            # written by the caller.
            new_active = await _fetch_flag(conn, "kill_switch_active")
            new_lock = await _fetch_flag(conn, "kill_switch_lock_mode")

    invalidate_cache()
    return {
        "active": new_active,
        "lock_mode": new_lock,
        "users_disabled": users_disabled,
    }


async def fetch_history(limit: int = 10) -> list[dict]:
    """Return the most recent ``kill_switch_history`` rows."""
    if limit <= 0:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT action, actor_id, reason, ts "
            "FROM kill_switch_history ORDER BY ts DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]
