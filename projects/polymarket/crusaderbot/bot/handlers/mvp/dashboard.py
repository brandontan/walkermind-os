"""MVP Dashboard handler — entry hub for the bot."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp._common import main_menu_kb
from ...keyboards.mvp.onboarding import new_user_dashboard_kb
from ...ui.tree import STATUS_NOT_SET, STATUS_PAUSED, STATUS_RUNNING, STATUS_STOPPED
from . import _users
from ._send import send_or_edit

log = logging.getLogger(__name__)


async def _read_dashboard(telegram_user) -> dict:
    """Aggregate dashboard data from existing project accessors."""
    data: dict = {
        "configured": False, "running": False, "paused": False,
        "today_pnl": 0.0, "today_trades": 0,
        "active_strategy": "⚡ Momentum", "copy_wallets_active": 0,
        "portfolio_value": 0.0, "open_count": 0,
    }
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return data
    data["paused"] = bool(u.get("paused"))
    # users.auto_trade_on is the canonical column (NOT "auto_trade_enabled",
    # which never existed → dashboard always read Stopped even while running).
    data["running"] = bool(u.get("auto_trade_on")) and not data["paused"]
    settings = await _users.fetch_settings(u["id"])
    preset = settings.get("active_preset")
    if preset:
        data["configured"] = True
        from ...presets import PRESET_CONFIG
        cfg = PRESET_CONFIG.get(preset, {})
        label = cfg.get("name") or str(preset).title().replace("_", " ")
        data["active_strategy"] = label
    data["portfolio_value"] = await _users.fetch_balance(u["id"])
    data["today_pnl"] = await _users.fetch_daily_pnl(u["id"])
    data["today_trades"] = await _users.fetch_today_trade_count(u["id"])
    data["open_count"] = await _users.fetch_open_position_count(u["id"])
    return data


async def show_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    d = await _read_dashboard(user)

    if not d["configured"]:
        text = mvp.render_dashboard_new_user()
        kb = new_user_dashboard_kb()
    elif d["paused"]:
        text = mvp.render_dashboard_paused(today_pnl=d["today_pnl"])
        kb = main_menu_kb(
            auto_on=True,
            paused=True,
            open_count=d.get("open_count", 0),
        )
    else:
        if d["running"]:
            status = STATUS_RUNNING
        elif d["configured"]:
            status = STATUS_STOPPED
        else:
            status = STATUS_NOT_SET
        text = mvp.render_dashboard_default(
            bot_status=status,
            today_pnl=d["today_pnl"],
            today_trades=d["today_trades"],
            active_strategy=d["active_strategy"],
            copy_wallets_active=d["copy_wallets_active"],
            portfolio_value=d["portfolio_value"],
        )
        kb = main_menu_kb(
            auto_on=d["running"],
            paused=False,
            open_count=d.get("open_count", 0),
            configured=d["configured"],
        )
    await send_or_edit(update, text, kb)


async def _dashboard_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await show_dashboard(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CommandHandler("home", show_dashboard))
    app.add_handler(CommandHandler("dashboard", show_dashboard))
    app.add_handler(CallbackQueryHandler(_dashboard_cb, pattern=r"^dashboard:"))
