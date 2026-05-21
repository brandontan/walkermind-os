"""portfolio_snapshots writer — wires the dormant `cb_portfolio` NOTIFY channel.

Migration `029_webtrader_tables.sql` installs `portfolio_snapshots` plus a
`AFTER INSERT` trigger that emits `cb_portfolio` (channel naming `cb_<table>`).
Until this module landed there was no Python writer, so WebTrader SSE
listeners subscribed to `cb_portfolio` received no traffic — see
`projects/polymarket/crusaderbot/reports/forge/runtime-spine-validation.md` §5.

The writer is invoked from two paths:

* `domain/execution/paper.py:close_position` — after the close transaction
  commits, so a fresh snapshot lands with each realised PnL event and the
  SSE bridge sees an immediate `cb_portfolio` push.
* `scheduler.py:snapshot_portfolios` — periodic tick (60s default) that
  refreshes every user with paper activity so open-position mark-to-market
  drift is reflected and the channel stays warm.

All work runs inside a single SELECT round-trip per user; the INSERT itself
is a second round-trip. Failures are caught and logged — the writer never
raises into its callers so a snapshot outage cannot block a trade close.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog

from ..database import get_pool

logger = logging.getLogger(__name__)
log = structlog.get_logger(__name__)


_METRICS_SQL = """
WITH bal AS (
    SELECT COALESCE(balance_usdc, 0) AS balance_usdc
      FROM wallets
     WHERE user_id = $1
),
open_pos AS (
    SELECT side, size_usdc, entry_price, current_price
      FROM positions
     WHERE user_id = $1 AND status = 'open'
),
open_agg AS (
    SELECT
        COUNT(*) AS open_count,
        COALESCE(SUM(
            size_usdc + CASE
                WHEN side = 'yes' AND entry_price > 0
                    THEN size_usdc * (current_price - entry_price) / entry_price
                WHEN side = 'no'  AND entry_price < 1
                    THEN size_usdc * (entry_price - current_price) / (1 - entry_price)
                ELSE 0
            END
        ), 0) AS open_mark_value
      FROM open_pos
),
pnl_today_q AS (
    SELECT COALESCE(SUM(amount_usdc), 0) AS pnl_today
      FROM ledger
     WHERE user_id = $1
       AND type IN ('trade_close', 'redeem', 'fee')
       AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'Asia/Jakarta')
                          AT TIME ZONE 'Asia/Jakarta'
),
pnl_7d_q AS (
    SELECT COALESCE(SUM(amount_usdc), 0) AS pnl_7d
      FROM ledger
     WHERE user_id = $1
       AND type IN ('trade_close', 'redeem', 'fee')
       AND created_at >= NOW() - INTERVAL '7 days'
)
SELECT
    bal.balance_usdc                        AS balance_usdc,
    bal.balance_usdc + open_agg.open_mark_value AS equity_usdc,
    pnl_today_q.pnl_today                   AS pnl_today,
    pnl_7d_q.pnl_7d                         AS pnl_7d,
    open_agg.open_count                     AS open_positions
  FROM bal, open_agg, pnl_today_q, pnl_7d_q
"""


_INSERT_SQL = """
INSERT INTO portfolio_snapshots (
    user_id, balance_usdc, equity_usdc, pnl_today, pnl_7d, open_positions
) VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id
"""


async def write_snapshot(user_id: UUID) -> Optional[UUID]:
    """Compute current portfolio metrics for ``user_id`` and INSERT a snapshot row.

    Returns the new ``portfolio_snapshots.id`` on success, or ``None`` when
    either the user has no wallet row (unknown user) or any DB error fires.
    Errors are logged at WARNING — the writer never raises so callers in the
    trade-close path are not blocked by a snapshot outage.

    The `AFTER INSERT` trigger on `portfolio_snapshots` emits the
    `cb_portfolio` NOTIFY payload as a side effect of the INSERT itself; no
    explicit NOTIFY call is needed here.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_METRICS_SQL, user_id)
            if row is None or row["balance_usdc"] is None:
                logger.info("portfolio_snapshots: skip user=%s (no wallet)", user_id)
                return None
            snapshot_id = await conn.fetchval(
                _INSERT_SQL,
                user_id,
                Decimal(str(row["balance_usdc"])),
                Decimal(str(row["equity_usdc"])),
                Decimal(str(row["pnl_today"])),
                Decimal(str(row["pnl_7d"])),
                int(row["open_positions"]),
            )
        log.info(
            "portfolio_snapshot_written",
            user_id=str(user_id),
            snapshot_id=str(snapshot_id),
            balance_usdc=str(row["balance_usdc"]),
            equity_usdc=str(row["equity_usdc"]),
            open_positions=int(row["open_positions"]),
        )
        return snapshot_id
    except Exception as exc:  # noqa: BLE001 — never raise into trade-close path
        logger.warning(
            "portfolio_snapshots.write_snapshot failed user=%s: %s", user_id, exc
        )
        return None


async def snapshot_active_users(*, lookback_hours: int = 24) -> int:
    """Snapshot every user with recent paper activity.

    Selection: any user with a `ledger` entry in the last ``lookback_hours``
    OR an open position. This keeps the per-tick fan-out bounded to active
    accounts rather than every row in `users` (which would be wasteful on a
    multi-thousand-user table during low-activity windows).

    Returns the number of snapshot rows written.
    """
    written = 0
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT u.id AS user_id
                  FROM users u
                  LEFT JOIN ledger l
                    ON l.user_id = u.id
                   AND l.created_at >= NOW() - ($1 || ' hours')::INTERVAL
                  LEFT JOIN positions p
                    ON p.user_id = u.id
                   AND p.status = 'open'
                 WHERE l.id IS NOT NULL OR p.id IS NOT NULL
                """,
                str(lookback_hours),
            )
        for row in rows:
            snapshot_id = await write_snapshot(row["user_id"])
            if snapshot_id is not None:
                written += 1
        log.info(
            "portfolio_snapshots_tick",
            users_scanned=len(rows),
            snapshots_written=written,
        )
    except Exception as exc:  # noqa: BLE001 — scheduler must not crash on this
        logger.warning("portfolio_snapshots.snapshot_active_users failed: %s", exc)
    return written
