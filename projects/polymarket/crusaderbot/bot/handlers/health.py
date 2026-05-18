"""Telegram /health command — live system health snapshot.

Shows bot status, last signal scan time, signals in the last hour, active jobs,
DB pool usage, and recent error count. Operator/ADMIN only.

Staleness thresholds:
    last scan > 5 min  → ⚠️  warning
    last scan > 15 min → 🚨 critical (scanner may be down)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

from ...config import get_settings
from ...database import get_pool
from ...domain.ops.kill_switch import is_active as kill_switch_is_active

logger = logging.getLogger(__name__)


def _wib_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=7)


async def _is_authorized(update: Update) -> bool:
    if update.effective_user is None:
        return False
    s = get_settings()
    if update.effective_user.id == s.OPERATOR_CHAT_ID:
        return True
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM user_tiers WHERE user_id=$1 AND tier='ADMIN'",
            update.effective_user.id,
        )
    return row is not None


async def _get_health_data() -> dict:
    pool = get_pool()
    now = datetime.now(timezone.utc)
    since_1h = now - timedelta(hours=1)

    async with pool.acquire() as conn:
        last_scan_row = await conn.fetchrow(
            "SELECT started_at FROM job_runs "
            "WHERE job_name='market_signal_scanner' AND status='success' "
            "ORDER BY started_at DESC LIMIT 1",
        )
        signals_1h = await conn.fetchval(
            "SELECT count(*) FROM signal_publications WHERE published_at > $1", since_1h,
        ) or 0
        markets_1h = await conn.fetchval(
            "SELECT count(*) FROM job_runs "
            "WHERE job_name='market_signal_scanner' AND started_at > $1", since_1h,
        ) or 0
        total_jobs = await conn.fetchval(
            "SELECT count(*) FROM job_runs WHERE started_at > $1", since_1h,
        ) or 0
        running_jobs = await conn.fetchval(
            "SELECT count(DISTINCT job_name) FROM job_runs WHERE started_at > $1",
            since_1h,
        ) or 0
        errors_1h = await conn.fetchval(
            "SELECT count(*) FROM job_runs WHERE status='error' AND started_at > $1",
            since_1h,
        ) or 0

    pool_obj = get_pool()
    pool_used = pool_obj.get_size() - pool_obj.get_idle_size()
    pool_max = pool_obj.get_size()

    last_scan_ago: str
    if last_scan_row:
        delta = now - last_scan_row["started_at"]
        minutes = int(delta.total_seconds() // 60)
        last_scan_ago = f"{minutes}m ago"
    else:
        last_scan_ago = "never"
        minutes = 9999

    return {
        "last_scan_ago": last_scan_ago,
        "last_scan_minutes": minutes,
        "signals_1h": int(signals_1h),
        "markets_1h": int(markets_1h),
        "running_jobs": int(running_jobs),
        "total_jobs_distinct": 17,  # known registered job count
        "pool_used": pool_used,
        "pool_max": pool_max,
        "errors_1h": int(errors_1h),
    }


async def health_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    try:
        data = await _get_health_data()
        kill_active = await kill_switch_is_active()
    except Exception as exc:
        logger.error("health_command: data fetch failed: %s", exc)
        await update.message.reply_text("❌ Health check failed — DB unreachable.")
        return

    now_wib = _wib_now()
    timestamp = now_wib.strftime("%Y-%m-%d %H:%M WIB")

    status_icon = "✅" if not kill_active else "🔴"
    status_text = "RUNNING" if not kill_active else "KILL SWITCH ACTIVE"

    mins = data["last_scan_minutes"]
    if mins >= 15:
        scan_flag = f"\n🚨 *Signal scan may be DOWN* — last run {data['last_scan_ago']}"
    elif mins >= 5:
        scan_flag = f"\n⚠️ Signal scan delayed — last run {data['last_scan_ago']}"
    else:
        scan_flag = ""

    msg = (
        f"🤖 *BOT HEALTH*\n"
        "──────────────────\n"
        f"Status:          {status_icon} {status_text}\n"
        f"Last scan:       {data['last_scan_ago']}\n"
        f"Signals (1h):    {data['signals_1h']}\n"
        f"Markets scanned: {data['markets_1h']}\n"
        f"Active jobs:     {data['running_jobs']}/{data['total_jobs_distinct']}\n"
        f"DB connections:  {data['pool_used']}/{data['pool_max']}\n"
        f"Errors (1h):     {data['errors_1h']}\n"
        "──────────────────\n"
        f"Last heartbeat: {timestamp}"
        f"{scan_flag}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")


__all__ = ["health_command"]
