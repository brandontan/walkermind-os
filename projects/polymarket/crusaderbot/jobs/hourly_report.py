"""Hourly system report — sent to all ADMIN-tier users via Telegram.

Fires every hour on the hour via APScheduler cron. Assembles a system snapshot
covering the last 60 minutes: scan count, signals found, trades opened/closed,
realized P&L, error count from job_runs, and uptime percentage.

A single Telegram send failure for one user does NOT abort the batch.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .. import notifications
from ..database import get_pool
from ..services.tiers import TIER_ADMIN

logger = logging.getLogger(__name__)

JOB_ID = "hourly_report"


async def _fetch_stats(since: datetime) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        scans = await conn.fetchval(
            "SELECT count(*) FROM job_runs WHERE job_name='market_signal_scanner' "
            "AND started_at > $1", since,
        ) or 0
        signals = await conn.fetchval(
            "SELECT count(*) FROM signal_publications WHERE published_at > $1", since,
        ) or 0
        trades_opened = await conn.fetchval(
            "SELECT count(*) FROM orders WHERE created_at > $1", since,
        ) or 0
        trades_closed = await conn.fetchval(
            "SELECT count(*) FROM positions WHERE closed_at > $1", since,
        ) or 0
        pnl_row = await conn.fetchrow(
            "SELECT COALESCE(SUM(pnl_usdc), 0) AS pnl "
            "FROM positions WHERE closed_at > $1", since,
        )
        hourly_pnl: Decimal = Decimal(str(pnl_row["pnl"] if pnl_row else 0))
        total_jobs = await conn.fetchval(
            "SELECT count(*) FROM job_runs WHERE started_at > $1", since,
        ) or 0
        error_jobs = await conn.fetchval(
            "SELECT count(*) FROM job_runs WHERE status='error' AND started_at > $1",
            since,
        ) or 0
    uptime_pct = (
        round((1 - error_jobs / total_jobs) * 100, 1) if total_jobs > 0 else 100.0
    )
    return {
        "scans": int(scans),
        "signals": int(signals),
        "trades_opened": int(trades_opened),
        "trades_closed": int(trades_closed),
        "hourly_pnl": hourly_pnl,
        "error_count": int(error_jobs),
        "uptime_pct": uptime_pct,
    }


async def _get_admin_telegram_ids() -> list[int]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.telegram_user_id
              FROM users u
              JOIN user_tiers t ON t.user_id = u.id
             WHERE t.tier = $1
            """,
            TIER_ADMIN,
        )
    return [int(r["telegram_user_id"]) for r in rows]


def _format_pnl(pnl: Decimal) -> str:
    sign = "+" if pnl >= 0 else ""
    return f"{sign}${float(pnl):.2f}"


async def run_job() -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
    time_str = now_wib.strftime("%H:%M WIB")

    try:
        stats = await _fetch_stats(since)
    except Exception as exc:
        logger.error("hourly_report: stats fetch failed: %s", exc)
        return

    admin_ids = await _get_admin_telegram_ids()
    if not admin_ids:
        logger.info("hourly_report: no ADMIN users found, skipping")
        return

    msg = (
        f"⚔️ <b>HOURLY REPORT — {html.escape(time_str)}</b>\n"
        "──────────────────\n"
        f"Scans:    {stats['scans']} completed\n"
        f"Signals:  {stats['signals']} found\n"
        f"Trades:   {stats['trades_opened']} opened / {stats['trades_closed']} closed\n"
        f"PNL:      {_format_pnl(stats['hourly_pnl'])} USDC\n"
        f"Errors:   {stats['error_count']}\n"
        f"Uptime:   {stats['uptime_pct']}%\n"
        "──────────────────"
    )

    sent = 0
    for tg_id in admin_ids:
        try:
            await notifications.send(tg_id, msg)
            sent += 1
        except Exception as exc:
            logger.warning("hourly_report: send failed tg_id=%s: %s", tg_id, exc)

    logger.info("hourly_report: sent to %d/%d admins", sent, len(admin_ids))


__all__ = ["run_job", "JOB_ID"]
