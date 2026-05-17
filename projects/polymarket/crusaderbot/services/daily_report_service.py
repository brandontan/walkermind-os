"""Daily P&L Report Service — APScheduler cron, per-user monospaced summary.

Sends each active user a formatted daily P&L report at a configurable hour
(env: DAILY_REPORT_HOUR, default 23 UTC). Users with zero closed trades today
are silently skipped. A delivery failure for one user never aborts the batch.

Uses existing ``positions`` and ``wallets`` tables — no new schema required.
Paper-only; ENABLE_LIVE_TRADING is not touched.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

from .. import notifications
from ..config import get_settings
from ..database import get_pool

logger = logging.getLogger(__name__)

JOB_ID = "daily_pnl_report"
_TIMEZONE_NAME = "Asia/Jakarta"


# ---------------------------------------------------------------------------
# Active user list
# ---------------------------------------------------------------------------


async def _list_active_users() -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, telegram_user_id FROM users "
            "WHERE telegram_user_id IS NOT NULL ORDER BY id",
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Daily stats
# ---------------------------------------------------------------------------


async def _fetch_daily_stats(user_id: UUID, today: date) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        # Closed-trade stats scoped to today only.
        stats_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'closed')               AS total_trades,
                COUNT(*) FILTER (WHERE status = 'closed' AND pnl_usdc > 0) AS wins,
                COUNT(*) FILTER (WHERE status = 'closed' AND pnl_usdc < 0) AS losses,
                COALESCE(SUM(pnl_usdc)  FILTER (WHERE status = 'closed'), 0) AS total_pnl,
                COALESCE(MAX(pnl_usdc)  FILTER (WHERE status = 'closed'), 0) AS best_trade,
                COALESCE(MIN(pnl_usdc)  FILTER (WHERE status = 'closed'), 0) AS worst_trade
            FROM positions
            WHERE user_id = $1
              AND DATE(closed_at) = $2
            """,
            user_id, today,
        )
        # Open positions are not date-scoped — count all currently open.
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE user_id = $1 AND status = 'open'",
            user_id,
        )
        balance = await conn.fetchval(
            "SELECT COALESCE(balance_usdc, 0) FROM wallets WHERE user_id = $1",
            user_id,
        )

    return {
        "total_trades": int(stats_row["total_trades"] or 0),
        "wins": int(stats_row["wins"] or 0),
        "losses": int(stats_row["losses"] or 0),
        "total_pnl": float(stats_row["total_pnl"] or 0),
        "best_trade": float(stats_row["best_trade"] or 0),
        "worst_trade": float(stats_row["worst_trade"] or 0),
        "open_positions": int(open_count or 0),
        "balance": float(balance or 0),
    }


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


def _format_daily_report(stats: dict[str, Any]) -> str:
    wins = stats["wins"]
    losses = stats["losses"]
    total = stats["total_trades"]
    win_rate = (wins / total * 100) if total > 0 else 0.0
    pnl = stats["total_pnl"]
    pnl_sign = "+" if pnl >= 0 else ""
    pnl_emoji = "\U0001f4c8" if pnl > 0 else "\U0001f4c9" if pnl < 0 else "⟖"

    date_str = _today_label()
    sep = "━" * 20

    return (
        f"\U0001f4ca <b>Daily Report</b>\n"
        f"<pre>"
        f"{sep}\n"
        f"Date:     {date_str}\n"
        f"Mode:     PAPER\n"
        f"{sep}\n"
        f"Trades:   {total}\n"
        f"Wins:     {wins}\n"
        f"Losses:   {losses}\n"
        f"Win Rate: {win_rate:.1f}%\n"
        f"{sep}\n"
        f"P&L:      {pnl_sign}${abs(pnl):.2f}  {pnl_emoji}\n"
        f"Best:     +${stats['best_trade']:.2f}\n"
        f"Worst:    -${abs(stats['worst_trade']):.2f}\n"
        f"{sep}\n"
        f"Balance:  ${stats['balance']:.2f}\n"
        f"Open:     {stats['open_positions']} positions\n"
        f"{sep}"
        f"</pre>"
    )


def _today_label() -> str:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(_TIMEZONE_NAME))
    except Exception:  # noqa: BLE001
        now = datetime.utcnow()
    return now.strftime("%b %d, %Y")


# ---------------------------------------------------------------------------
# Per-user send
# ---------------------------------------------------------------------------


async def _send_daily_report(user: dict[str, Any]) -> None:
    user_id: UUID = user["id"]
    tg_id: int = int(user["telegram_user_id"])

    today = date.today()
    stats = await _fetch_daily_stats(user_id, today)

    if stats["total_trades"] == 0:
        return

    text = _format_daily_report(stats)
    await notifications.send(tg_id, text)


# ---------------------------------------------------------------------------
# Job entry point
# ---------------------------------------------------------------------------


async def daily_pnl_report_job() -> dict[str, Any]:
    """Send daily P&L report to all active users with trades today.

    Returns aggregate stats that the APScheduler job_runs listener stores
    in ``job_runs.metadata`` for operator dashboards.
    """
    users = await _list_active_users()
    sent = 0
    skipped = 0
    failed = 0

    for user in users:
        try:
            tg_id = user.get("telegram_user_id")
            if tg_id is None:
                skipped += 1
                continue

            stats = await _fetch_daily_stats(user["id"], date.today())
            if stats["total_trades"] == 0:
                skipped += 1
                continue

            text = _format_daily_report(stats)
            ok = await notifications.send(int(tg_id), text)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as exc:  # noqa: BLE001 — never abort the batch
            failed += 1
            logger.error(
                "daily_report: failed user=%s err=%s",
                user.get("id"), exc, exc_info=True,
            )

    result = {
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "total_users": len(users),
    }
    logger.info("daily_pnl_report done: %s", result)
    return result
