"""Weekly Insights — Monday 08:00 Asia/Jakarta auto-push to all active users.

Derives category/signal performance from the last 7 days of closed paper
positions.  No AI API.  No schema changes — reads from existing positions
and markets tables.

Public API:
    format_weekly_insights(data) -> str
    run_once() -> dict
    run_job() -> None

Job ID: weekly_insights
Cron:   Monday 08:00 Asia/Jakarta
"""
from __future__ import annotations

import html
import logging
from decimal import Decimal
from uuid import UUID

from .. import notifications
from ..database import get_pool

logger = logging.getLogger(__name__)

JOB_ID = "weekly_insights"
_TIMEZONE = "Asia/Jakarta"


# ---------------- Data fetch -------------------------------------------------


async def _fetch_weekly_stats(user_id: UUID) -> dict:
    """Assemble category + signal breakdown for the last 7 days."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Category breakdown: win rate and total PnL per category
        cat_rows = await conn.fetch(
            """
            SELECT
                COALESCE(m.category, 'uncategorised') AS category,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE p.pnl_usdc > 0) AS wins,
                COALESCE(SUM(p.pnl_usdc), 0) AS total_pnl
            FROM positions p
            LEFT JOIN markets m ON m.id = p.market_id
            WHERE p.user_id = $1
              AND p.status = 'closed'
              AND p.mode = 'paper'
              AND p.closed_at >= NOW() - INTERVAL '7 days'
              AND p.pnl_usdc IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) >= 1
            ORDER BY 1
            """,
            user_id,
        )

        # Signal (strategy_type) breakdown: total PnL per signal.
        # strategy_type lives on orders, not positions — LEFT JOIN to reach it.
        sig_rows = await conn.fetch(
            """
            SELECT
                COALESCE(o.strategy_type, 'unknown') AS signal,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE p.pnl_usdc > 0) AS wins,
                COALESCE(SUM(p.pnl_usdc), 0) AS total_pnl
            FROM positions p
            LEFT JOIN orders o ON o.id = p.order_id
            WHERE p.user_id = $1
              AND p.status = 'closed'
              AND p.mode = 'paper'
              AND p.closed_at >= NOW() - INTERVAL '7 days'
              AND p.pnl_usdc IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) >= 1
            ORDER BY 1
            """,
            user_id,
        )

        # Overall 7-day totals
        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total_trades,
                COUNT(*) FILTER (WHERE pnl_usdc > 0) AS wins,
                COALESCE(SUM(pnl_usdc), 0) AS total_pnl
            FROM positions
            WHERE user_id = $1
              AND status = 'closed'
              AND mode = 'paper'
              AND closed_at >= NOW() - INTERVAL '7 days'
              AND pnl_usdc IS NOT NULL
            """,
            user_id,
        )

    categories: list[dict] = []
    for r in cat_rows:
        total = int(r["total"] or 0)
        wins = int(r["wins"] or 0)
        win_rate = wins / total if total > 0 else 0.0
        categories.append({
            "name": r["category"],
            "total": total,
            "wins": wins,
            "win_rate": win_rate,
            "total_pnl": Decimal(str(r["total_pnl"] or 0)),
        })

    signals: list[dict] = []
    for r in sig_rows:
        total = int(r["total"] or 0)
        wins = int(r["wins"] or 0)
        win_rate = wins / total if total > 0 else 0.0
        signals.append({
            "name": r["signal"],
            "total": total,
            "wins": wins,
            "win_rate": win_rate,
            "total_pnl": Decimal(str(r["total_pnl"] or 0)),
        })

    total_trades = int((summary or {}).get("total_trades") or 0)
    total_wins = int((summary or {}).get("wins") or 0)
    total_pnl = Decimal(str((summary or {}).get("total_pnl") or 0))

    return {
        "total_trades": total_trades,
        "total_wins": total_wins,
        "total_pnl": total_pnl,
        "categories": categories,
        "signals": signals,
    }


# ---------------- Formatter --------------------------------------------------


def _fmt_pnl(v: Decimal) -> str:
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(v):.2f}"


def _safe(s: str) -> str:
    return html.escape(s.replace("_", " "))


def format_weekly_insights(data: dict) -> str:
    """Render weekly insights as a Telegram HTML message."""
    total = data["total_trades"]
    wins = data["total_wins"]
    total_pnl = data["total_pnl"]
    categories: list[dict] = data["categories"]
    signals: list[dict] = data["signals"]

    if total == 0:
        return (
            "\U0001f4ca <b>Weekly Insights</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No closed paper trades in the last 7 days."
        )

    win_rate = int(wins / total * 100) if total else 0
    pnl_str = _fmt_pnl(total_pnl)

    lines: list[str] = [
        "\U0001f4ca <b>Weekly Insights — Last 7 Days</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "\U0001f3c6 <b>Summary</b>",
        f"├─ Trades: {total} ({wins}W / {total - wins}L)",
        f"├─ Win Rate: {win_rate}%",
        f"└─ Net P&amp;L: {pnl_str}",
        "",
    ]

    # Category section
    if categories:
        best_cat = max(categories, key=lambda c: c["win_rate"])
        worst_cat = min(categories, key=lambda c: c["win_rate"])

        lines += [
            "\U0001f3f7 <b>By Category</b>",
            f"├─ Best:  <b>{_safe(best_cat['name'])}</b>"
            f" — {int(best_cat['win_rate'] * 100)}% WR"
            f" ({best_cat['wins']}/{best_cat['total']})",
            f"└─ Worst: <b>{_safe(worst_cat['name'])}</b>"
            f" — {int(worst_cat['win_rate'] * 100)}% WR"
            f" ({worst_cat['wins']}/{worst_cat['total']})",
            "",
        ]

    # Signal section
    if signals:
        best_sig = max(signals, key=lambda s: s["total_pnl"])
        worst_sig = min(signals, key=lambda s: s["total_pnl"])

        lines += [
            "\U0001f4e1 <b>By Signal</b>",
            f"├─ Top:   <b>{_safe(best_sig['name'])}</b>"
            f" — {_fmt_pnl(best_sig['total_pnl'])}",
            f"└─ Worst: <b>{_safe(worst_sig['name'])}</b>"
            f" — {_fmt_pnl(worst_sig['total_pnl'])}",
        ]

    return "\n".join(lines)


# ---------------- Job entry points -------------------------------------------


async def _list_active_users() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, telegram_user_id FROM users "
            "WHERE telegram_user_id IS NOT NULL "
            "AND paused = FALSE AND auto_trade_on = TRUE ORDER BY id",
        )
    return [dict(r) for r in rows]


async def run_once() -> dict:
    """Send weekly insights to all active users. Returns batch stats."""
    users = await _list_active_users()
    sent = 0
    failed = 0
    skipped = 0

    for u in users:
        user_id = u["id"]
        tg_id = u["telegram_user_id"]
        try:
            data = await _fetch_weekly_stats(user_id)
            text = format_weekly_insights(data)
            ok = await notifications.send(int(tg_id), text)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            logger.error(
                "weekly_insights failed user=%s err=%s", user_id, exc, exc_info=True,
            )

    return {
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "total_users": len(users),
    }


async def run_job() -> None:
    """APScheduler entry point."""
    stats = await run_once()
    logger.info("weekly_insights done: %s", stats)
