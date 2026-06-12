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
from ...wallet.ledger import get_live_balance, live_ledger_filter_sql
from . import live_checklist

MIN_LIVE_AUTOTRADE_BALANCE_USDC = Decimal("5")
# Fresh paper practice bankroll seeded when a paper session is reset, matching
# users.seed_paper_capital ($1,000 initial credit). Returning to PAPER after a
# LIVE stint must show this, not the stale pre-live bankroll.
PAPER_STARTING_BALANCE_USDC = Decimal("1000")
PAPER_ARCHIVED_MODE = "paper_archived"
PAPER_ARCHIVE_EXIT_REASON = "paper_to_live_switch"
PAPER_SESSION_RESET_NOTE = "Paper wallet — session reset $1,000 credit"

# Machine-readable refusal reasons surfaced by the shared start guard so each
# arming surface can render its own copy without re-deriving the decision.
REASON_LIVE_NOT_READY = "live_not_ready"
REASON_LIVE_NO_FUNDS = "live_no_funds"


@dataclass(frozen=True)
class PaperToLiveResult:
    from_mode: str
    trading_mode: str
    live_balance_usdc: Decimal
    auto_trade_on: bool
    archived_positions: int
    archived_orders: int
    archived_notifications: int
    archived_ledger_rows: int
    paper_session_reset: bool
    paper_balance_after_reset_usdc: Decimal
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


@dataclass(frozen=True)
class LiveAutotradeStartGate:
    """Shared decision for "may this user START live Auto-Trade right now?".

    Every arming surface — WebTrader ``/autotrade/toggle``, Telegram
    activation, MVP Auto-Trade — routes through
    :func:`evaluate_live_autotrade_start` so the live arming gate is enforced
    identically and can never drift between surfaces. Paper users are always
    allowed (``is_live`` False): the guard is a no-op for them and existing
    paper behaviour is untouched. For live users the guard requires every
    required ``live_checklist`` gate to pass AND confirmed available live
    USDC.e >= $5 (paper / pending / reserved / in-position / withdraw-pending
    balances are excluded by ``get_live_balance``). The guard never starts
    Auto-Trade and never flips any platform live guard — it only decides.
    """

    trading_mode: str
    is_live: bool
    allowed: bool
    reason: str  # "" when allowed, else REASON_LIVE_NOT_READY / REASON_LIVE_NO_FUNDS
    live_balance_usdc: Decimal
    enough_balance: bool
    checklist: Optional[live_checklist.ChecklistResult]

    @property
    def checklist_ready(self) -> bool:
        return self.checklist is None or self.checklist.ready_for_live


async def _read_trading_mode(
    user_id: UUID, conn: Optional[asyncpg.Connection] = None,
) -> str:
    sql = "SELECT trading_mode FROM user_settings WHERE user_id=$1"
    if conn is not None:
        mode = await conn.fetchval(sql, user_id)
    else:
        pool = get_pool()
        async with pool.acquire() as c:
            mode = await c.fetchval(sql, user_id)
    return str(mode or "paper")


async def evaluate_live_autotrade_start(
    user_id: UUID,
    *,
    trading_mode: Optional[str] = None,
    conn: Optional[asyncpg.Connection] = None,
) -> LiveAutotradeStartGate:
    """Decide whether the user may start LIVE Auto-Trade.

    Paper users pass through unconditionally (the caller still applies its
    own kill-switch / preset checks). Live users must clear the required
    activation checklist and hold >= $5 confirmed available live USDC.e.
    The checklist refusal takes precedence over the funding refusal so the
    user fixes operator/strategy gates before being told to deposit.

    ``trading_mode`` may be supplied by callers that already resolved it
    (the Telegram/MVP surfaces read settings first) to skip a redundant DB
    read; when ``None`` the guard reads it itself.
    """
    if trading_mode is None:
        trading_mode = await _read_trading_mode(user_id, conn)
    if trading_mode != "live":
        return LiveAutotradeStartGate(
            trading_mode=trading_mode,
            is_live=False,
            allowed=True,
            reason="",
            live_balance_usdc=Decimal("0"),
            enough_balance=True,
            checklist=None,
        )

    checklist = await live_checklist.evaluate(user_id)
    balance, enough = await live_autotrade_balance_status(user_id, conn)
    if not checklist.ready_for_live:
        reason, allowed = REASON_LIVE_NOT_READY, False
    elif not enough:
        reason, allowed = REASON_LIVE_NO_FUNDS, False
    else:
        reason, allowed = "", True
    return LiveAutotradeStartGate(
        trading_mode=trading_mode,
        is_live=True,
        allowed=allowed,
        reason=reason,
        live_balance_usdc=balance,
        enough_balance=enough,
        checklist=checklist,
    )


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
    * archive pre-switch per-user AlertCenter rows (``dismissed=TRUE``) and
      acknowledge the alert watermark so LIVE notification context starts clean.

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
            alert_status = await c.execute(
                """
                UPDATE system_alerts
                   SET dismissed = TRUE
                 WHERE user_id = $1
                   AND dismissed = FALSE
                   AND created_at <= NOW()
                """,
                user_id,
            )
            # ---- Paper session reset (#1792 full scope) -------------------
            # The paper positions/orders are archived above, but the paper
            # LEDGER rows have no mode column — they are "not live" rows, so
            # without this they stayed in the paper wallet feed and kept
            # wallets.balance_usdc at the stale pre-live bankroll (e.g.
            # 904.16). Archive the user's active paper ledger rows and reseed
            # a fresh $1,000 paper bankroll so PAPER -> LIVE -> PAPER returns a
            # clean practice session. Only on a genuine PAPER -> LIVE
            # transition (re-enabling live has no paper session to reset).
            paper_filter = f"NOT {live_ledger_filter_sql('l')}"
            archived_ledger = 0
            paper_session_reset = False
            paper_balance_after_reset = PAPER_STARTING_BALANCE_USDC
            if from_mode != "live":
                ledger_status = await c.execute(
                    f"""
                    UPDATE ledger AS l
                       SET archived = TRUE
                     WHERE l.user_id = $1
                       AND l.archived = FALSE
                       AND {paper_filter}
                    """,
                    user_id,
                )
                archived_ledger = _status_count(ledger_status)
                # Live cash is unaffected by archiving paper rows (they fail
                # the live predicate). wallets.balance_usdc = paper + live by
                # construction, so reset paper to the fresh bankroll while
                # preserving the live component.
                live_now = await get_live_balance(user_id, c)
                new_wallet_balance = PAPER_STARTING_BALANCE_USDC + live_now
                await c.execute(
                    "UPDATE wallets SET balance_usdc = $2 WHERE user_id = $1",
                    user_id,
                    new_wallet_balance,
                )
                # Fresh, non-archived paper deposit row so the returning paper
                # wallet feed opens on the clean $1,000 credit.
                await c.execute(
                    """
                    INSERT INTO ledger (user_id, type, amount_usdc, note, archived)
                    VALUES ($1, 'deposit', $2, $3, FALSE)
                    """,
                    user_id,
                    PAPER_STARTING_BALANCE_USDC,
                    PAPER_SESSION_RESET_NOTE,
                )
                paper_session_reset = True
            balance = await get_live_balance(user_id, c)
        return PaperToLiveResult(
            from_mode=from_mode,
            trading_mode="live",
            live_balance_usdc=balance,
            auto_trade_on=False,
            archived_positions=_status_count(pos_status),
            archived_orders=_status_count(order_status),
            archived_notifications=_status_count(alert_status),
            archived_ledger_rows=archived_ledger,
            paper_session_reset=paper_session_reset,
            paper_balance_after_reset_usdc=paper_balance_after_reset,
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
