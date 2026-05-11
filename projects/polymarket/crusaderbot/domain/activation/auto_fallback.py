"""Track F — Auto-fallback monitor.

Background job that polls every 60 seconds. If the count of
execution-error audit events in the trailing 60-second window exceeds
ERROR_THRESHOLD, every user currently in live trading mode is
automatically switched to paper mode. Each switch is:

- Written to ``user_settings.trading_mode = 'paper'``.
- Logged to ``mode_change_events`` with reason AUTO_FALLBACK.
- Notified to the operator via Telegram.

The job is idempotent: users already in paper mode are skipped.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from ...database import get_pool
from ... import notifications
from .live_opt_in_gate import ModeChangeReason, write_mode_change_event

logger = logging.getLogger(__name__)

ERROR_THRESHOLD: int = 5
LOOKBACK_SECONDS: int = 60
JOB_ID = "auto_fallback_monitor"

# Actions emitted by domain/execution/live.py on submission failure.
LIVE_ERROR_ACTIONS: tuple[str, ...] = (
    "live_pre_submit_failed",
    "live_submit_ambiguous",
    "live_post_submit_db_error",
)


async def get_recent_error_count(lookback_seconds: int = LOOKBACK_SECONDS) -> int:
    """Count live-execution error events in the last ``lookback_seconds`` from audit.log."""
    since = datetime.now(timezone.utc) - timedelta(seconds=lookback_seconds)
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM audit.log "
                "WHERE action = ANY($1) AND ts >= $2",
                list(LIVE_ERROR_ACTIONS), since,
            )
        return int(count or 0)
    except Exception as exc:
        logger.error("auto_fallback error count query failed err=%s", exc)
        return 0


async def get_live_mode_users() -> list[dict]:
    """Return all users whose trading_mode is 'live'."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT us.user_id, u.telegram_user_id "
                "FROM user_settings us "
                "JOIN users u ON u.id = us.user_id "
                "WHERE us.trading_mode = 'live'",
            )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("auto_fallback live-user query failed err=%s", exc)
        return []


async def _switch_user_to_paper(user_id: UUID) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_settings SET trading_mode='paper', updated_at=NOW() "
            "WHERE user_id=$1",
            user_id,
        )


async def run_auto_fallback_check() -> None:
    """Main entry point called by the scheduler every 60 seconds."""
    error_count = await get_recent_error_count()
    if error_count <= ERROR_THRESHOLD:
        return

    logger.warning(
        "auto_fallback triggered error_count=%d threshold=%d",
        error_count, ERROR_THRESHOLD,
    )

    live_users = await get_live_mode_users()
    if not live_users:
        return

    switched: list[int] = []
    for row in live_users:
        user_id: UUID = row["user_id"]
        tg_id: Optional[int] = row.get("telegram_user_id")
        try:
            await _switch_user_to_paper(user_id)
            await write_mode_change_event(
                user_id=user_id,
                from_mode="live",
                to_mode="paper",
                reason=ModeChangeReason.AUTO_FALLBACK,
            )
            if tg_id:
                switched.append(tg_id)
        except Exception as exc:
            logger.error(
                "auto_fallback switch failed user=%s err=%s", user_id, exc,
            )

    try:
        await notifications.notify_operator(
            f"⚠️ AUTO-FALLBACK triggered. "
            f"error_count={error_count} in last {LOOKBACK_SECONDS}s "
            f"(threshold={ERROR_THRESHOLD}). "
            f"Switched {len(switched)} user(s) to paper mode."
        )
    except Exception as exc:
        logger.error("auto_fallback operator notify failed err=%s", exc)
