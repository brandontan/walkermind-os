"""Operator-facing daily P&L summary — once-per-day Telegram page (WARP-76 H2).

Distinct from :mod:`jobs.daily_pnl_summary`, which pushes a *per-user* review to
every opted-in user. This job sends a single **aggregate** line to the operator
channel (``OPERATOR_CHAT_ID``) so the operator gets a daily heartbeat of paper
trading activity without scraping Fly logs:

  * positions opened today
  * positions closed today (with win / loss split)
  * net realized P&L delta across all paper closes today
  * distinct active users (opened a position today)

Paper-scoped (``mode='paper'``) explicitly so the aggregate stays paper-only
after a future live activation. "Today" is anchored to Asia/Jakarta, matching
the per-user summary semantics. The operator page is fail-soft: a Telegram
outage is logged, never raised, so a notify failure cannot crash the scheduler.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from .. import notifications
from ..database import get_pool

logger = logging.getLogger(__name__)


JOB_ID = "operator_daily_summary"
TIMEZONE_NAME = "Asia/Jakarta"


async def collect_metrics() -> dict:
    """Aggregate today's paper-trading activity across all users.

    One row, FILTER-clause counts so a zero-activity day returns zeros instead
    of NULL. Mirrors the ``date_trunc`` Asia/Jakarta "today" idiom used by
    :mod:`jobs.daily_pnl_summary`.
    """
    today = (
        "date_trunc('day', NOW() AT TIME ZONE $1) AT TIME ZONE $1"
    )
    closed_today = (
        f"status='closed' AND closed_at IS NOT NULL AND closed_at >= {today}"
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND opened_at >= {today}) "
            f"    AS opened_today, "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND {closed_today}) "
            f"    AS closed_today, "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND {closed_today} "
            f"    AND pnl_usdc > 0) AS wins_today, "
            f"  COUNT(*) FILTER (WHERE mode='paper' AND {closed_today} "
            f"    AND pnl_usdc < 0) AS losses_today, "
            f"  COALESCE(SUM(pnl_usdc) FILTER (WHERE mode='paper' AND "
            f"    {closed_today}), 0) AS net_delta, "
            f"  COUNT(DISTINCT user_id) FILTER (WHERE mode='paper' "
            f"    AND opened_at >= {today}) AS active_users "
            f"FROM positions",
            TIMEZONE_NAME,
        )
    row = row or {}
    return {
        "opened_today": int(row.get("opened_today") or 0),
        "closed_today": int(row.get("closed_today") or 0),
        "wins_today": int(row.get("wins_today") or 0),
        "losses_today": int(row.get("losses_today") or 0),
        "net_delta": Decimal(row.get("net_delta") or 0),
        "active_users": int(row.get("active_users") or 0),
    }


def _fmt_signed(value: Decimal) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):.2f}"


def format_operator_summary(metrics: dict) -> str:
    """Render the operator page (ParseMode.HTML)."""
    net = metrics["net_delta"]
    net_d = net if isinstance(net, Decimal) else Decimal(str(net))
    return (
        "📊 <b>DAILY PAPER P&amp;L — OPERATOR SUMMARY</b>\n"
        f"opened today: <b>{metrics['opened_today']}</b>\n"
        f"closed today: <b>{metrics['closed_today']}</b> "
        f"(W <b>{metrics['wins_today']}</b> / L <b>{metrics['losses_today']}</b>)\n"
        f"net delta: <b>{_fmt_signed(net_d)}</b>\n"
        f"active users: <b>{metrics['active_users']}</b>"
    )


async def run_job() -> dict:
    """APScheduler entry point — collect aggregates, page the operator.

    Returns the metrics dict so the scheduler listener captures it into the
    ``job_runs`` row. The operator page is best-effort: a notify failure is
    logged and swallowed so it never crashes the scheduled sweep.
    """
    metrics = await collect_metrics()
    text = format_operator_summary(metrics)
    try:
        await notifications.notify_operator(text)
    except Exception as exc:  # noqa: BLE001 — page is best-effort
        logger.error("operator_daily_summary notify failed: %s", exc)
    logger.info("operator_daily_summary done: %s", metrics)
    return metrics


__all__ = ["run_job", "collect_metrics", "format_operator_summary", "JOB_ID"]
