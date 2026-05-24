"""MVP Settings handler — Trading Mode / Risk / Notifications / Account / Advanced."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards_v2.mvp import settings as kb
from ...ui.tree import LIVE, PAPER
from . import _users
from ._send import callback_parts, send_or_edit

log = logging.getLogger(__name__)


async def _read_settings(telegram_user) -> dict:
    s: dict = {
        "trading_mode": PAPER,
        "daily_loss_limit": 20.0, "max_position_pct": 10,
        "max_concurrent": 3, "auto_pause_enabled": True,
        "notif_trade_opened": True, "notif_trade_closed": True,
        "notif_risk_alerts": True, "notif_daily_summary": True,
        "notif_market_alerts": False,
        "wallet_status": "Connected", "api_status": "🟢 Healthy",
        "subscription": "MVP", "debug_enabled": False,
    }
    if telegram_user is None:
        return s
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return s
    mode_flag = bool(u.get("live_mode_enabled") or u.get("live_trading_enabled"))
    s["trading_mode"] = LIVE if mode_flag else PAPER
    return s


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(update, mvp.render_settings_home(trading_mode=s["trading_mode"]), kb.home_kb())


async def show_trading_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(update, mvp.render_settings_trading_mode(current=s["trading_mode"]), kb.trading_mode_kb())


async def show_live_gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Live mode is locked at the UX layer per blueprint 23.2 — UI surface only.

    Execution guard (`ENABLE_LIVE_TRADING`) is untouched; this screen never
    flips it. Activation flows route to existing live_gate handler.
    """
    await send_or_edit(update, mvp.render_settings_live_gate(), kb.live_gate_kb())


async def show_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(
        update,
        mvp.render_settings_risk_controls(
            daily_loss_limit=s["daily_loss_limit"],
            max_position_pct=s["max_position_pct"],
            max_concurrent=s["max_concurrent"],
            auto_pause_enabled=s["auto_pause_enabled"],
        ),
        kb.risk_controls_kb(),
    )


async def show_notifications(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(
        update,
        mvp.render_settings_notifications(
            trade_opened=s["notif_trade_opened"],
            trade_closed=s["notif_trade_closed"],
            risk_alerts=s["notif_risk_alerts"],
            daily_summary=s["notif_daily_summary"],
            market_alerts=s["notif_market_alerts"],
        ),
        kb.notifications_kb(),
    )


async def show_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(
        update,
        mvp.render_settings_account(
            wallet_status=s["wallet_status"],
            mode=s["trading_mode"],
            api_status=s["api_status"],
            subscription=s["subscription"],
        ),
        kb.account_kb(),
    )


async def show_advanced(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(update, mvp.render_settings_advanced(debug_enabled=s["debug_enabled"]), kb.advanced_kb())


async def _settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "mode":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "live":
            # Show live gate; does NOT enable live execution.
            await show_live_gate(update, ctx); return
        if sub == "paper":
            await show_trading_mode(update, ctx); return
        await show_trading_mode(update, ctx); return
    if screen == "risk":
        await show_risk(update, ctx); return
    if screen == "notifications":
        await show_notifications(update, ctx); return
    if screen == "account":
        await show_account(update, ctx); return
    if screen == "advanced":
        await show_advanced(update, ctx); return
    if screen == "copy_wallet":
        # Delegate to copy_wallet home.
        from . import copy_wallet as cw
        await cw.show_home(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_settings_cb, pattern=r"^settings:"))
