"""Two-layer live-activation composition — read-only predicate.

``is_live_execution_allowed`` answers a single question: may THIS user route a
real order to the CLOB right now? It is a pure composition over existing state
and writes NOTHING. The fail direction on any uncertainty is False (→ paper).

All of the following must hold (short-circuit AND, in this order):

  1. ``ENABLE_LIVE_TRADING`` env guard is truthy (Fly-level hard stop — read,
     never written here).
  2. The GLOBAL operator toggle ``global_live_trading_enabled`` is True
     (cached read via domain.ops.global_live_gate — Condition 2).
  3. The PER-USER opt-in is live and funded: a ``user_settings`` row exists for
     ``user_id`` with ``paper_mode_override`` False, ``trading_mode == 'live'``,
     and ``live_capital_cap_usdc > 0``.

The per-user layer here is a read-only mirror of the state that the existing
WebTrader ``/live/enable`` flow + ``live_opt_in_gate`` already maintain; this
module does not duplicate that flow, it only evaluates its result.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

import asyncpg

from ...config import get_settings
from ...database import get_pool
from ..ops.global_live_gate import is_global_live_enabled

logger = logging.getLogger(__name__)


async def _read_user_live_state(
    conn: asyncpg.Connection, user_id: UUID,
) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        "SELECT trading_mode, paper_mode_override, live_capital_cap_usdc "
        "FROM user_settings WHERE user_id = $1",
        user_id,
    )


async def is_live_execution_allowed(
    user_id: UUID,
    conn: Optional[asyncpg.Connection] = None,
) -> bool:
    """Return True only when env guard, global toggle, AND per-user opt-in pass.

    Read-only. Never raises for a missing user row — a user with no
    ``user_settings`` row is simply not opted in (returns False). Pass ``conn``
    to share a transaction; otherwise a short-lived pooled connection is used
    for the single user_settings read (the global flag is its own cached read).
    """
    # [1] Env hard stop — never written here.
    if not get_settings().ENABLE_LIVE_TRADING:
        return False

    # [2] Global operator toggle (cached; fail-safe to False). Forward ``conn``
    # so a caller sharing a transaction sees a consistent (cache-bypassed) read.
    if not await is_global_live_enabled(conn):
        return False

    # [3] Per-user opt-in + funded cap.
    if conn is not None:
        row = await _read_user_live_state(conn, user_id)
    else:
        pool = get_pool()
        async with pool.acquire() as c:
            row = await _read_user_live_state(c, user_id)

    if row is None:
        return False
    if bool(row["paper_mode_override"]):
        return False
    if (row["trading_mode"] or "") != "live":
        return False
    cap = row["live_capital_cap_usdc"] or 0
    if float(cap) <= 0:
        return False

    return True
