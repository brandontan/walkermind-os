"""Phase 5 UX Rebuild — Dashboard (Screen 02).

Trigger: /start (returning user), menu:dashboard callback.
All data live from DB.
"""
from __future__ import annotations

import html
import logging
from decimal import Decimal

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import upsert_user
from ...wallet.ledger import daily_pnl, get_balance
from ..keyboards import p5_dashboard_kb
from ..messages import dashboard_text

logger = logging.getLogger(__name__)


async def _fetch_stats(user_id) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        pos = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(size_usdc), 0) AS positions_value,
                COUNT(*) FILTER (WHERE current_price IS NOT NULL
                                   AND current_price > entry_price) AS winning,
                COUNT(*) FILTER (WHERE current_price IS NOT NULL
                                   AND current_price < entry_price) AS losing
            FROM positions
            WHERE user_id = $1 AND status = 'open'
            """,
            user_id,
        )
        trades = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                        AS total_trades,
                COUNT(*) FILTER (WHERE pnl_usdc > 0)           AS wins,
                COUNT(*) FILTER (WHERE pnl_usdc IS NOT NULL
                                   AND pnl_usdc <= 0)          AS losses,
                COALESCE(SUM(size_usdc), 0)                    AS total_volume,
                COUNT(DISTINCT market_id)                       AS markets_traded
            FROM positions
            WHERE user_id = $1 AND status != 'open'
            """,
            user_id,
        )
        pnl = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(amount_usdc) FILTER (
                    WHERE type IN ('trade_close','redeem','fee')
                      AND created_at >= NOW() - INTERVAL '7 days'), 0)  AS pnl_7d,
                COALESCE(SUM(amount_usdc) FILTER (
                    WHERE type IN ('trade_close','redeem','fee')
                      AND created_at >= NOW() - INTERVAL '30 days'), 0) AS pnl_30d,
                COALESCE(SUM(amount_usdc) FILTER (
                    WHERE type IN ('trade_close','redeem','fee')), 0)    AS pnl_all
            FROM ledger
            WHERE user_id = $1
            """,
            user_id,
        )
        sett = await conn.fetchrow(
            "SELECT active_preset, risk_profile FROM user_settings WHERE user_id = $1",
            user_id,
        )
    return {
        "positions_value": Decimal(str(pos["positions_value"])),
        "winning":         int(pos["winning"]),
        "losing":          int(pos["losing"]),
        "total_trades":    int(trades["total_trades"]),
        "wins":            int(trades["wins"]),
        "losses":          int(trades["losses"]),
        "total_volume":    Decimal(str(trades["total_volume"])),
        "markets_traded":  int(trades["markets_traded"]),
        "pnl_7d":          Decimal(str(pnl["pnl_7d"])),
        "pnl_30d":         Decimal(str(pnl["pnl_30d"])),
        "pnl_all":         Decimal(str(pnl["pnl_all"])),
        "active_preset":   sett["active_preset"] if sett else None,
        "risk_profile":    sett["risk_profile"] if sett else "balanced",
    }


def _preset_display(preset_key: str | None) -> tuple[str, str, str, str]:
    """Return (emoji, name, risk_emoji, risk_label) for a preset key."""
    from ..presets import PRESET_CONFIG
    if not preset_key:
        return "⚙️", "Not configured", "⚫", "—"
    cfg = PRESET_CONFIG.get(preset_key)
    if not cfg:
        return "⚙️", preset_key, "⚫", "—"
    return cfg["emoji"], cfg["name"], cfg["risk_emoji"], cfg["risk_label"]


async def _build_dashboard_message(user: dict) -> tuple[str, bool]:
    """Return (message_text, has_preset). All data live from DB."""
    bal = await get_balance(user["id"])
    pnl_today = await daily_pnl(user["id"])
    st = await _fetch_stats(user["id"])

    preset_key = st["active_preset"]
    p_emoji, p_name, r_emoji, r_label = _preset_display(preset_key)

    bal_d = Decimal(str(bal))
    total_equity = bal_d + st["positions_value"]

    # pnl today percentage
    pnl_today_d = Decimal(str(pnl_today))
    pnl_today_pct = (
        float(pnl_today_d) / float(bal_d) * 100 if bal_d > 0 else 0.0
    )
    pnl_7d_pct = (
        float(st["pnl_7d"]) / float(bal_d) * 100 if bal_d > 0 else 0.0
    )
    pnl_30d_pct = (
        float(st["pnl_30d"]) / float(bal_d) * 100 if bal_d > 0 else 0.0
    )

    win_rate = (
        float(st["wins"]) / st["total_trades"] * 100
        if st["total_trades"] > 0 else 0.0
    )

    text = dashboard_text(
        balance=bal_d,
        positions_value=st["positions_value"],
        total_equity=total_equity,
        wins=st["wins"],
        losses=st["losses"],
        pnl_today=pnl_today_d,
        pnl_today_pct=pnl_today_pct,
        pnl_7d=st["pnl_7d"],
        pnl_7d_pct=pnl_7d_pct,
        pnl_30d=st["pnl_30d"],
        pnl_30d_pct=pnl_30d_pct,
        pnl_alltime=st["pnl_all"],
        total_trades=st["total_trades"],
        win_rate=win_rate,
        total_volume=st["total_volume"],
        markets_count=st["markets_traded"],
        autotrade_on=user.get("auto_trade_on", False),
        preset_key=preset_key,
        preset_emoji=p_emoji,
        preset_name=p_name,
        risk_emoji=r_emoji,
        risk_label=r_label,
    )
    return text, bool(preset_key)


# ── Public entry points ────────────────────────────────────────────────────────

async def show_dashboard(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    user: dict | None = None,
) -> None:
    """Message-based dashboard render (from /start or command)."""
    if update.effective_user is None:
        return
    if user is None:
        user = await upsert_user(update.effective_user.id, update.effective_user.username)
    text, has_preset = await _build_dashboard_message(user)
    target = update.message or (
        update.callback_query.message if update.callback_query else None
    )
    if target is None:
        return
    await target.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=p5_dashboard_kb(has_preset),
    )


async def show_dashboard_for_cb(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    refresh: bool = False,
) -> None:
    """Callback-query-compatible dashboard render (edit or reply)."""
    q = update.callback_query
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    text, has_preset = await _build_dashboard_message(user)
    kb = p5_dashboard_kb(has_preset)

    if q is not None and q.message is not None:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ── Command handler alias ──────────────────────────────────────────────────────

async def dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await show_dashboard(update, ctx)


# ── Legacy callback shim — routes dashboard:* callbacks ───────────────────────

async def dashboard_nav_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes legacy dashboard:* callbacks from non-rewritten handlers."""
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub in ("main", "refresh"):
        await show_dashboard_for_cb(update, ctx)
    elif sub in ("auto", "autotrade"):
        from .autotrade import show_autotrade
        await show_autotrade(update, ctx)
    elif sub in ("portfolio", "trades"):
        from .trades import show_trades
        await show_trades(update, ctx)
    elif sub == "wallet":
        from .wallet import wallet_root_cb
        await wallet_root_cb(update, ctx)
    elif sub == "settings":
        from .settings import settings_hub_root
        await settings_hub_root(update, ctx)
    elif sub == "insights":
        from .pnl_insights import pnl_insights_command
        await pnl_insights_command(update, ctx)
    elif sub == "monitor":
        await show_dashboard_for_cb(update, ctx, refresh=True)
    elif sub == "start_auto":
        from .autotrade import show_autotrade
        await show_autotrade(update, ctx)
    elif sub == "stop":
        from ...users import set_auto_trade
        if update.effective_user is None:
            return
        user = await upsert_user(update.effective_user.id, update.effective_user.username)
        await set_auto_trade(user["id"], False)
        await show_dashboard_for_cb(update, ctx)
    else:
        await show_dashboard_for_cb(update, ctx)


async def autotrade_toggle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy autotrade:toggle callback — kept for backward compat."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    from ...users import set_auto_trade
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    new_state = not user.get("auto_trade_on", False)
    await set_auto_trade(user["id"], new_state)
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    text, has_preset = await _build_dashboard_message(user)
    try:
        await q.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=p5_dashboard_kb(has_preset),
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def close_position_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy position:close:* callback handler."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    from .trades import close_ask_cb
    await close_ask_cb(update, ctx)


async def activity(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy /activity command — routes to trades screen."""
    from .trades import show_trades
    await show_trades(update, ctx)
