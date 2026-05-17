"""Daily P&L Summary — once-per-day Telegram push.

Runs as an APScheduler cron job at 23:00 Asia/Jakarta. For every user
with the opt-in flag still ON, the job assembles a summary covering
today's realized / unrealized P&L, fees paid, open position count,
total exposure as a fraction of balance, the user's trading mode, and
paper-mode activity counts (opened today, closed today with W/L).

Fast Track Track E (#960) adds the paper-mode activity counts and an
explicit no-trade empty state so the daily review is readable on days
with zero activity. R12's realized/unrealized/fees/exposure semantics
are preserved verbatim.

Opt-in toggle is stored in ``system_settings`` keyed
``daily_summary_off:{user_id}``. Default is ON — absence of the row
counts as enabled, so the toggle is migration-free. Users opt out via
``/summary_off`` (and back in via ``/summary_on``).

The job is intentionally graceful: a Telegram send failure for one user
does NOT abort the batch. Per-user errors are logged and counted; the
batch always returns aggregate stats and writes one ``job_runs`` row.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from .. import notifications
from ..database import get_pool
from ..users import user_notifications_enabled

logger = logging.getLogger(__name__)


JOB_ID = "daily_pnl_summary"
TOGGLE_KEY_PREFIX = "daily_summary_off:"
TIMEZONE_NAME = "Asia/Jakarta"


# ---------------- Opt-in toggle (system_settings, no migration) -------------


async def is_summary_enabled(user_id: UUID) -> bool:
    """Return True when the user has NOT opted out (default ON)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM system_settings WHERE key=$1",
            f"{TOGGLE_KEY_PREFIX}{user_id}",
        )
    if row is None:
        return True
    raw = (row["value"] or "").strip().lower()
    # Stored as 'true' when the user has explicitly opted OUT. We keep the
    # off-flag instead of an on-flag so the absence of a row → default ON.
    return raw not in {"true", "1", "yes", "on"}


async def set_summary_enabled(user_id: UUID, enabled: bool) -> None:
    """Persist the user's opt-in choice.

    Always upserts the key — even when enabling — so subsequent reads
    are deterministic regardless of whether the row existed before.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO system_settings (key, value, updated_at) "
            "VALUES ($1, $2, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, "
            "updated_at=NOW()",
            f"{TOGGLE_KEY_PREFIX}{user_id}",
            "false" if enabled else "true",
        )


# ---------------- Per-user summary build ------------------------------------


async def _fetch_user_summary_row(user_id: UUID) -> dict:
    """Single-shot read assembling the inputs for ``format_summary``.

    Done in one DB connection (multiple queries) rather than a single
    monster join so each piece can be tested independently and so a
    schema rename in one source doesn't break the others.
    """
    pool = get_pool()
    ledger_today_filter = (
        "created_at >= date_trunc('day', NOW() AT TIME ZONE $2) "
        "AT TIME ZONE $2"
    )
    # Realized P&L is read from positions.pnl_usdc rather than the ledger
    # because both paper.close_position and live.close_position credit the
    # ledger with the FULL proceeds (size + pnl) under T_TRADE_CLOSE.
    # Summing the ledger would report cash returned, not realized profit.
    # ``positions.pnl_usdc`` carries the actual P&L for both exit closes
    # (status='closed', closed_at set) and resolution-redemption closes
    # (same path), so a single closed_at-bounded sum is correct for both.
    closed_today_filter = (
        "closed_at >= date_trunc('day', NOW() AT TIME ZONE $2) "
        "AT TIME ZONE $2"
    )
    opened_today_filter = (
        "opened_at >= date_trunc('day', NOW() AT TIME ZONE $2) "
        "AT TIME ZONE $2"
    )
    async with pool.acquire() as conn:
        realized = await conn.fetchval(
            f"SELECT COALESCE(SUM(pnl_usdc), 0) FROM positions "
            f"WHERE user_id=$1 AND status='closed' "
            f"AND closed_at IS NOT NULL AND {closed_today_filter}",
            user_id, TIMEZONE_NAME,
        )
        fees = await conn.fetchval(
            f"SELECT COALESCE(SUM(amount_usdc), 0) FROM ledger "
            f"WHERE user_id=$1 AND type = 'fee' AND {ledger_today_filter}",
            user_id, TIMEZONE_NAME,
        )
        positions = await conn.fetch(
            "SELECT side, size_usdc, entry_price, current_price "
            "FROM positions WHERE user_id=$1 AND status='open'",
            user_id,
        )
        balance = await conn.fetchval(
            "SELECT COALESCE(balance_usdc, 0) FROM wallets WHERE user_id=$1",
            user_id,
        )
        mode = await conn.fetchval(
            "SELECT trading_mode FROM user_settings WHERE user_id=$1",
            user_id,
        )
        # Paper-mode activity counts (Fast Track Track E #960). One row,
        # four COUNT(*) FILTER clauses so a no-trade day still returns
        # zeros instead of NULL. mode='paper' is enforced explicitly so
        # the count breakdown stays paper-scoped after live activation.
        counts_row = await conn.fetchrow(
            f"SELECT "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND {opened_today_filter}) "
            f"    AS opened_today, "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND status='closed' "
            f"    AND closed_at IS NOT NULL AND {closed_today_filter}) "
            f"    AS closed_today, "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND status='closed' "
            f"    AND closed_at IS NOT NULL AND pnl_usdc > 0 "
            f"    AND {closed_today_filter}) AS wins_today, "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND status='closed' "
            f"    AND closed_at IS NOT NULL AND pnl_usdc < 0 "
            f"    AND {closed_today_filter}) AS losses_today "
            f"FROM positions WHERE user_id=$1",
            user_id, TIMEZONE_NAME,
        )

    realized_d = Decimal(realized or 0)
    # Fees are stored as negative debits in the ledger. Surface as a
    # positive paid-amount in the summary.
    fees_d = abs(Decimal(fees or 0))
    balance_d = Decimal(balance or 0)

    open_count = len(positions)
    exposure = Decimal(0)
    unrealized = Decimal(0)
    for p in positions:
        size = Decimal(p["size_usdc"] or 0)
        exposure += size
        entry = Decimal(p["entry_price"] or 0)
        current = Decimal(p["current_price"] or 0)
        if entry <= 0 or current <= 0:
            continue
        # ``positions.entry_price`` and ``positions.current_price`` are
        # stored side-specific: a NO position holds the NO market price
        # at entry (set from the strategy's side-specific cand.price)
        # and the NO mark on every tick (registry.update_current_price
        # persists the NO-side value via OpenPositionForExit.current_price).
        # The unrealized P&L is therefore (current - entry) / entry for
        # both sides — no YES/NO complement reversal. A NO bought at 0.40
        # and marked at 0.60 yields ret = +0.5 (gain), which matches the
        # USDC value of the held NO shares.
        ret = (current - entry) / entry
        unrealized += size * ret

    exposure_pct = (
        Decimal(0)
        if balance_d <= 0
        else (exposure / balance_d) * Decimal(100)
    )

    counts = counts_row or {}
    return {
        "realized": realized_d,
        "unrealized": unrealized,
        "fees": fees_d,
        "open_count": open_count,
        "exposure_pct": exposure_pct,
        "mode": (mode or "paper").upper(),
        "opened_today": int(counts.get("opened_today") or 0),
        "closed_today": int(counts.get("closed_today") or 0),
        "wins_today": int(counts.get("wins_today") or 0),
        "losses_today": int(counts.get("losses_today") or 0),
    }


def _fmt_signed(value: Decimal) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):.2f}"


def format_summary(*, date_label: str, realized: Decimal, unrealized: Decimal,
                   fees: Decimal, open_count: int, exposure_pct: Decimal,
                   mode: str, opened_today: int = 0, closed_today: int = 0,
                   wins_today: int = 0, losses_today: int = 0) -> str:
    # No-trade empty state: zero paper activity, zero open positions, AND
    # zero realized/unrealized P&L and zero fees. The realized/unrealized/
    # fees totals stay mode-agnostic (R12 semantics preserved) so a
    # live-mode close on a paper-zero day still contributes to them —
    # the stricter gate prevents the compact form from hiding nonzero
    # performance (Codex P1 review on PR #962). Track E (#960).
    if (opened_today == 0 and closed_today == 0 and open_count == 0
            and realized == 0 and unrealized == 0 and fees == 0):
        return (
            f"📊 <b>Daily Summary — {html.escape(date_label)}</b>\n"
            f"No paper trades today. Mode: <code>{html.escape(mode)}</code>."
        )
    return (
        f"📊 <b>Daily Summary — {html.escape(date_label)}</b>\n"
        f"Realized P&amp;L  : <code>{_fmt_signed(realized)}</code>\n"
        f"Unrealized P&amp;L: <code>{_fmt_signed(unrealized)}</code>\n"
        f"Fees paid     : <code>${fees:.2f}</code>\n"
        f"Trades opened : <code>{opened_today}</code>\n"
        f"Trades closed : <code>{closed_today}</code> (W:{wins_today} L:{losses_today})\n"
        f"Open positions: <code>{open_count}</code>\n"
        f"Exposure      : <code>{exposure_pct:.1f}%</code>\n"
        f"Mode          : <code>{html.escape(mode)}</code>"
    )


async def build_summary_for_user(user_id: UUID,
                                 date_label: str) -> str:
    data = await _fetch_user_summary_row(user_id)
    return format_summary(date_label=date_label, **data)


# ---------------- Job entry point -------------------------------------------


async def _list_recipient_users() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, telegram_user_id FROM users ORDER BY id",
        )
    return [dict(r) for r in rows]


def _today_label() -> str:
    """Render today (Asia/Jakarta) as YYYY-MM-DD without bringing in pytz."""
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(TIMEZONE_NAME))
    except Exception:  # noqa: BLE001 — zoneinfo always present on 3.11+
        now = datetime.utcnow()
    return now.strftime("%Y-%m-%d")


async def run_once() -> dict:
    """Iterate every opted-in user, send their summary, return stats.

    A Telegram delivery failure on one user does NOT short-circuit the
    rest of the batch. The returned dict is also written to ``job_runs``
    via the wrapping ``run_job`` so /jobs surfaces the per-user counts
    without a separate logging surface.
    """
    date_label = _today_label()
    users = await _list_recipient_users()
    sent = 0
    skipped_disabled = 0
    skipped_no_telegram = 0
    failed = 0
    for u in users:
        user_id = u["id"]
        tg_id = u["telegram_user_id"]
        try:
            if not await is_summary_enabled(user_id):
                skipped_disabled += 1
                continue
            if not await user_notifications_enabled(user_id):
                skipped_disabled += 1
                continue
            if tg_id is None:
                skipped_no_telegram += 1
                continue
            text = await build_summary_for_user(user_id, date_label)
            ok = await notifications.send(int(tg_id), text)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as exc:  # noqa: BLE001 — never abort the batch
            failed += 1
            logger.error(
                "daily_pnl_summary failed user=%s err=%s",
                user_id, exc, exc_info=True,
            )
    return {
        "sent": sent,
        "skipped_disabled": skipped_disabled,
        "skipped_no_telegram": skipped_no_telegram,
        "failed": failed,
        "total_users": len(users),
        "date": date_label,
    }


async def run_job() -> None:
    """APScheduler entry point.

    Wraps :func:`run_once` so the listener-driven ``job_runs`` row gets
    a meaningful error column on a fatal failure (a per-user failure is
    swallowed inside ``run_once``). The standalone ``job_runs`` row that
    the scheduler listener writes already records start/finish; this
    function does not duplicate that bookkeeping.
    """
    stats = await run_once()
    logger.info("daily_pnl_summary done: %s", stats)
