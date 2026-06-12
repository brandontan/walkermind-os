"""Self-serve PAPER -> LIVE mode transition helpers.

The switch is intentionally separate from live order activation:
users may opt into LIVE mode after explicit consent, but Auto-Trade is
forced OFF and later start/resume checks must prove operator guards,
risk confirmation, and confirmed available live USDC.e.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from ...database import get_pool
from ...wallet.ledger import get_live_balance

MIN_LIVE_AUTOTRADE_BALANCE_USDC = Decimal("5")
PAPER_ARCHIVED_MODE = "paper_archived"
PAPER_ARCHIVE_EXIT_REASON = "paper_to_live_switch"


@dataclass(frozen=True)
class PaperToLiveResult:
    from_mode: str
    trading_mode: str
    live_balance_usdc: Decimal
    auto_trade_on: bool
    archived_positions: int
    archived_orders: int
    alerts_acknowledged: bool
    waiting_for_deposit: bool


def has_min_live_autotrade_balance(balance: Decimal | float | int | str) -> bool:
    """Return True only for confirmed available live USDC.e >= $5."""
    return Decimal(str(balance)) >= MIN_LIVE_AUTOTRADE_BALANCE_USDC


async def live_autotrade_balance_status(
    user_id: UUID,
    conn: Optional[asyncpg.Connection] = None,
) -> tuple[Decimal, bool]:
    """Return (confirmed available live balance, meets $5 minimum)."""
    balance = await get_live_balance(user_id, conn)
    return balance, has_min_live_autotrade_balance(balance)


async def enable_live_self_serve(
    user_id: UUID,
    *,
    live_capital_cap_usdc: float = 0.0,
    conn: Optional[asyncpg.Connection] = None,
) -> PaperToLiveResult:
    """Flip a user to LIVE without migrating any paper accounting truth.

    Effects are deliberately narrow and transactional:
    * write ``user_settings.trading_mode='live'`` + mirror override false;
    * force ``users.auto_trade_on=FALSE``;
    * archive current paper simulation positions/orders away from user-facing
      paper/live queries by moving their mode to ``paper_archived``;
    * acknowledge pre-switch user-scoped alerts so LIVE AlertCenter starts clean.

    The helper never flips platform live guards and never starts Auto-Trade.
    """

    async def _run(c: asyncpg.Connection) -> PaperToLiveResult:
        async with c.transaction():
            before = await c.fetchval(
                "SELECT trading_mode FROM user_settings WHERE user_id=$1",
                user_id,
            )
            from_mode = str(before or "paper")
            await c.execute(
                """
                INSERT INTO user_settings (
                    user_id, trading_mode, paper_mode_override,
                    live_capital_cap_usdc, alerts_ack_at, updated_at
                ) VALUES ($1, 'live', FALSE, $2, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    trading_mode = 'live',
                    paper_mode_override = FALSE,
                    live_capital_cap_usdc = $2,
                    alerts_ack_at = NOW(),
                    updated_at = NOW()
                """,
                user_id,
                float(live_capital_cap_usdc or 0.0),
            )
            await c.execute(
                "UPDATE users SET auto_trade_on = FALSE WHERE id = $1",
                user_id,
            )
            pos_status = await c.execute(
                """
                UPDATE positions
                   SET mode = $2,
                       status = CASE
                           WHEN status IN ('open', 'pending_settlement') THEN 'closed'
                           ELSE status
                       END,
                       exit_reason = CASE
                           WHEN status IN ('open', 'pending_settlement') THEN $3
                           ELSE exit_reason
                       END,
                       closed_at = CASE
                           WHEN status IN ('open', 'pending_settlement')
                                AND closed_at IS NULL THEN NOW()
                           ELSE closed_at
                       END
                 WHERE user_id = $1
                   AND mode = 'paper'
                """,
                user_id,
                PAPER_ARCHIVED_MODE,
                PAPER_ARCHIVE_EXIT_REASON,
            )
            order_status = await c.execute(
                """
                UPDATE orders
                   SET mode = $2
                 WHERE user_id = $1
                   AND mode = 'paper'
                """,
                user_id,
                PAPER_ARCHIVED_MODE,
            )
            balance = await get_live_balance(user_id, c)
        return PaperToLiveResult(
            from_mode=from_mode,
            trading_mode="live",
            live_balance_usdc=balance,
            auto_trade_on=False,
            archived_positions=_status_count(pos_status),
            archived_orders=_status_count(order_status),
            alerts_acknowledged=True,
            waiting_for_deposit=not has_min_live_autotrade_balance(balance),
        )

    if conn is not None:
        return await _run(conn)
    pool = get_pool()
    async with pool.acquire() as c:
        return await _run(c)


def _status_count(status: str) -> int:
    """Parse asyncpg status strings like 'UPDATE 3'."""
    try:
        return int(str(status).split()[-1])
    except (IndexError, ValueError):
        return 0
