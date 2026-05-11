"""PNL Insights — on-demand performance analytics surface.

Surfaces rich trading statistics derived from the closed positions log:
win-rate, profit factor, average win/loss, best/worst trade, current
streak, and a 7-day summary.  Data comes entirely from existing
``positions`` and ``markets`` tables; no schema migration required.

Handler: /insights command + insights:refresh callback
Tier:    ALLOWLISTED (Tier 2+)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import upsert_user
from ..keyboards import insights_kb
from ..tier import Tier, has_tier, tier_block_message

logger = logging.getLogger(__name__)

_TITLE_MAX = 40


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_signed_usdc(value: Decimal | None) -> str:
    """Format a USDC PnL value as a signed dollar string, e.g. +$8.50 or -$4.20."""
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):.2f}"


def _safe_md(s: str) -> str:
    """Replace legacy Markdown reserved chars that break italic/bold markers.

    Telegram legacy Markdown treats _text_ as italic only at word boundaries;
    embedded underscores in market titles close the italic early and corrupt
    the message rendering.  Replace the four reserved chars with safe
    alternatives so dynamic market titles never break the Markdown structure.
    """
    return (
        s.replace("\\", "")
         .replace("_", " ")
         .replace("*", "")
         .replace("`", "")
         .replace("[", "")
    )


def _compute_streak(pnl_values: list[Decimal]) -> tuple[str, int]:
    """Return (direction, length) for the current streak, newest-first input.

    direction is 'win' (pnl > 0) or 'loss' (pnl <= 0).
    Returns ('win', 0) when pnl_values is empty.
    """
    if not pnl_values:
        return "win", 0
    direction = "win" if pnl_values[0] > 0 else "loss"
    count = 0
    for v in pnl_values:
        is_win = v > 0
        if direction == "win" and is_win:
            count += 1
        elif direction == "loss" and not is_win:
            count += 1
        else:
            break
    return direction, count


async def _fetch_insights(user_id: UUID) -> dict:
    """Assemble all insight metrics in one DB connection (4 queries)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'closed' AND mode = 'paper')
                    AS total_closed,
                COUNT(*) FILTER (WHERE status = 'closed' AND mode = 'paper'
                                   AND pnl_usdc > 0)
                    AS wins,
                COUNT(*) FILTER (WHERE status = 'closed' AND mode = 'paper'
                                   AND pnl_usdc <= 0)
                    AS losses,
                COALESCE(SUM(pnl_usdc)
                    FILTER (WHERE status = 'closed' AND mode = 'paper'
                              AND pnl_usdc > 0), 0)
                    AS gross_wins,
                COALESCE(SUM(ABS(pnl_usdc))
                    FILTER (WHERE status = 'closed' AND mode = 'paper'
                              AND pnl_usdc <= 0), 0)
                    AS gross_losses,
                MAX(pnl_usdc) FILTER (WHERE status = 'closed' AND mode = 'paper')
                    AS best_pnl,
                MIN(pnl_usdc) FILTER (WHERE status = 'closed' AND mode = 'paper')
                    AS worst_pnl,
                COALESCE(AVG(pnl_usdc)
                    FILTER (WHERE status = 'closed' AND mode = 'paper'
                              AND pnl_usdc > 0), 0)
                    AS avg_win,
                COALESCE(ABS(AVG(pnl_usdc))
                    FILTER (WHERE status = 'closed' AND mode = 'paper'
                              AND pnl_usdc <= 0), 0)
                    AS avg_loss,
                COUNT(*) FILTER (
                    WHERE status = 'closed' AND mode = 'paper'
                      AND closed_at >= NOW() - INTERVAL '7 days')
                    AS trades_7d,
                COALESCE(SUM(pnl_usdc) FILTER (
                    WHERE status = 'closed' AND mode = 'paper'
                      AND closed_at >= NOW() - INTERVAL '7 days'), 0)
                    AS pnl_7d
            FROM positions WHERE user_id = $1
            """,
            user_id,
        )
        best_row = await conn.fetchrow(
            """
            SELECT COALESCE(m.question, p.market_id) AS title
              FROM positions p LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1 AND p.status = 'closed' AND p.mode = 'paper'
             ORDER BY p.pnl_usdc DESC NULLS LAST LIMIT 1
            """,
            user_id,
        )
        worst_row = await conn.fetchrow(
            """
            SELECT COALESCE(m.question, p.market_id) AS title
              FROM positions p LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1 AND p.status = 'closed' AND p.mode = 'paper'
             ORDER BY p.pnl_usdc ASC NULLS LAST LIMIT 1
            """,
            user_id,
        )
        streak_rows = await conn.fetch(
            """
            SELECT pnl_usdc FROM positions
             WHERE user_id = $1 AND status = 'closed' AND mode = 'paper'
               AND pnl_usdc IS NOT NULL
             ORDER BY closed_at DESC NULLS LAST LIMIT 25
            """,
            user_id,
        )

    total_closed = int(stats["total_closed"] or 0)
    wins = int(stats["wins"] or 0)
    losses = int(stats["losses"] or 0)
    gross_wins = Decimal(str(stats["gross_wins"] or 0))
    gross_losses = Decimal(str(stats["gross_losses"] or 0))
    best_pnl = (
        Decimal(str(stats["best_pnl"])) if stats["best_pnl"] is not None else None
    )
    worst_pnl = (
        Decimal(str(stats["worst_pnl"])) if stats["worst_pnl"] is not None else None
    )
    avg_win = Decimal(str(stats["avg_win"] or 0))
    avg_loss = Decimal(str(stats["avg_loss"] or 0))
    trades_7d = int(stats["trades_7d"] or 0)
    pnl_7d = Decimal(str(stats["pnl_7d"] or 0))

    streak_values = [Decimal(str(r["pnl_usdc"])) for r in streak_rows]
    streak_dir, streak_len = _compute_streak(streak_values)

    return {
        "total_closed": total_closed,
        "wins": wins,
        "losses": losses,
        "gross_wins": gross_wins,
        "gross_losses": gross_losses,
        "best_pnl": best_pnl,
        "worst_pnl": worst_pnl,
        "best_title": (
            _truncate(best_row["title"], _TITLE_MAX) if best_row else None
        ),
        "worst_title": (
            _truncate(worst_row["title"], _TITLE_MAX) if worst_row else None
        ),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "trades_7d": trades_7d,
        "pnl_7d": pnl_7d,
        "streak_dir": streak_dir,
        "streak_len": streak_len,
    }


def format_insights(data: dict) -> str:
    """Render insights data as a Telegram Markdown message."""
    if data["total_closed"] == 0:
        return (
            "\U0001f4ca *PNL Insights*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No closed trades yet. Start paper trading to see your insights."
        )

    total = data["total_closed"]
    wins = data["wins"]
    losses = data["losses"]
    win_rate = int(wins / total * 100) if total else 0

    gross_wins = data["gross_wins"]
    gross_losses = data["gross_losses"]
    if gross_losses > 0:
        pf_str = f"{float(gross_wins / gross_losses):.2f}"
    elif gross_wins > 0:
        pf_str = "∞"
    else:
        pf_str = "N/A"

    best_pnl = data["best_pnl"]
    worst_pnl = data["worst_pnl"]
    best_str = _fmt_signed_usdc(best_pnl)
    worst_str = _fmt_signed_usdc(worst_pnl)
    best_title = _safe_md(data.get("best_title") or "—")
    worst_title = _safe_md(data.get("worst_title") or "—")

    avg_win = data["avg_win"]
    avg_loss = data["avg_loss"]

    streak_dir = data["streak_dir"]
    streak_len = data["streak_len"]
    if streak_len == 0:
        streak_str = "—"
    else:
        icon = "\U0001f525" if streak_dir == "win" else "❄️"
        label = "win" if streak_dir == "win" else "loss"
        streak_str = f"{icon} {streak_len} {label}{'s' if streak_len > 1 else ''}"

    pnl_7d = data["pnl_7d"]
    trades_7d = data["trades_7d"]
    pnl_7d_str = _fmt_signed_usdc(pnl_7d)

    return (
        "\U0001f4ca *PNL Insights*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "\U0001f3c6 *Performance*\n"
        f"├─ Closed Trades: {total} ({wins}W / {losses}L)\n"
        f"├─ Win Rate: {win_rate}%\n"
        f"└─ Profit Factor: {pf_str}\n\n"
        "\U0001f4b0 *Averages*\n"
        f"├─ Avg Win: +${avg_win:.2f}\n"
        f"└─ Avg Loss: -${avg_loss:.2f}\n\n"
        "\U0001f3af *Best Trade*\n"
        f"├─ P&L: {best_str}\n"
        f"└─ _{best_title}_\n\n"
        "\U0001f4c9 *Worst Trade*\n"
        f"├─ P&L: {worst_str}\n"
        f"└─ _{worst_title}_\n\n"
        "⚡ *Streak*\n"
        f"└─ Current: {streak_str}\n\n"
        "\U0001f4c5 *Last 7 Days*\n"
        f"├─ Trades: {trades_7d}\n"
        f"└─ P&L: {pnl_7d_str}"
    )


async def pnl_insights_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username
    )
    if not has_tier(user["access_tier"], Tier.ALLOWLISTED):
        await update.message.reply_text(tier_block_message(Tier.ALLOWLISTED))
        return
    data = await _fetch_insights(user["id"])
    await update.message.reply_text(
        format_insights(data),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=insights_kb(),
    )


async def insights_cb(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username
    )
    if not has_tier(user["access_tier"], Tier.ALLOWLISTED):
        await q.answer(tier_block_message(Tier.ALLOWLISTED), show_alert=True)
        return
    data = await _fetch_insights(user["id"])
    await q.message.reply_text(
        format_insights(data),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=insights_kb(),
    )
