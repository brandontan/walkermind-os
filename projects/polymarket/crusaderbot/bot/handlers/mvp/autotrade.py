"""MVP Auto Trade handler — full-auto strategy engine surface."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp import autotrade as kb
from ...ui.tree import STATUS_NOT_SET, STATUS_PAUSED, STATUS_RUNNING, STATUS_STOPPED
from . import _users
from ._send import callback_parts, send_or_edit

log = logging.getLogger(__name__)

_DEFAULT_STRATEGY = "⚡ Momentum"
_DEFAULT_RISK = "🟡 Balanced"
_DEFAULT_CAPITAL = 100.0


def _flow(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    """Per-user wizard state stored in PTB `user_data`."""
    if "mvp_auto_flow" not in ctx.user_data:
        ctx.user_data["mvp_auto_flow"] = {
            "strategy": _DEFAULT_STRATEGY,
            "capital": _DEFAULT_CAPITAL,
            "risk": _DEFAULT_RISK,
        }
    return ctx.user_data["mvp_auto_flow"]


async def _read_state(telegram_user) -> dict:
    state: dict = {
        "uuid": None,
        "configured": False,
        "running": False, "paused": False,
        "strategy": _DEFAULT_STRATEGY, "risk": _DEFAULT_RISK,
        "capital": _DEFAULT_CAPITAL, "pnl_today": 0.0,
        "executions": 0, "win_rate": 0,
    }
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return state
    state["uuid"] = u["id"]
    state["paused"] = bool(u.get("paused"))
    state["running"] = bool(u.get("auto_trade_enabled")) and not state["paused"]
    settings = await _users.fetch_settings(u["id"])
    preset = settings.get("active_preset")
    if preset:
        state["configured"] = True
        from ...presets import PRESET_CONFIG
        cfg = PRESET_CONFIG.get(preset, {})
        label = cfg.get("name") or str(preset).title().replace("_", " ")
        state["strategy"] = label
    state["pnl_today"] = await _users.fetch_daily_pnl(u["id"])
    return state


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    s = await _read_state(user) if user else {
        "configured": False, "running": False, "paused": False,
        "strategy": _DEFAULT_STRATEGY,
        "risk": _DEFAULT_RISK, "capital": _DEFAULT_CAPITAL,
        "pnl_today": 0.0, "executions": 0, "win_rate": 0,
    }
    if s["running"]:
        status = STATUS_RUNNING
    elif s["paused"]:
        status = STATUS_PAUSED
    elif s.get("configured"):
        status = STATUS_STOPPED
    else:
        status = STATUS_NOT_SET
    text = mvp.render_autotrade_home(
        status=status,
        strategy=s["strategy"],
        capital=s["capital"],
        risk=s["risk"],
        pnl_today=s["pnl_today"],
        executions=s["executions"],
        win_rate=s["win_rate"],
    )
    await send_or_edit(update, text, kb.home_kb(running=s["running"]))


async def show_quick_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_autotrade_quick_start(), kb.quick_start_kb())


async def show_configure_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_autotrade_configure_strategy(), kb.configure_strategy_kb())


async def show_configure_capital(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    f = _flow(ctx)
    await send_or_edit(update, mvp.render_autotrade_configure_capital(current=f["capital"]), kb.configure_capital_kb())


async def show_configure_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_autotrade_configure_risk(), kb.configure_risk_kb())


async def show_configure_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    f = _flow(ctx)
    text = mvp.render_autotrade_configure_review(
        strategy=f["strategy"], capital=f["capital"], risk=f["risk"],
    )
    await send_or_edit(update, text, kb.configure_review_kb())


async def show_strategy_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    s = await _read_state(user) if user else {
        "strategy": _DEFAULT_STRATEGY, "running": False, "capital": _DEFAULT_CAPITAL,
        "pnl_today": 0.0, "executions": 0,
    }
    status = STATUS_RUNNING if s["running"] else STATUS_NOT_SET
    text = mvp.render_autotrade_strategy_status(
        strategy=s["strategy"], status=status, capital=s["capital"],
        pnl_today=s["pnl_today"], trades=s.get("executions", 0),
    )
    await send_or_edit(update, text, kb.strategy_status_kb(running=s["running"]))


async def show_pause_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_autotrade_pause_confirm(), kb.pause_confirm_kb())


async def show_resume_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_autotrade_resume_confirm(), kb.resume_confirm_kb())


async def do_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    f = _flow(ctx)
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            await _users.set_paused(u["id"], False)
            await _users.set_auto_trade(u["id"], True)
    text = mvp.render_notif_bot_started(
        strategy=f["strategy"], capital=f["capital"], risk=f["risk"],
    )
    await send_or_edit(update, text, kb.strategy_status_kb(running=True))
    from ...keyboards.mvp._common import main_menu_kb
    msg = update.effective_message
    if msg is not None:
        await msg.reply_text(".", reply_markup=main_menu_kb(auto_on=True, paused=False, open_count=0))


async def do_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            await _users.set_paused(u["id"], True)
    await show_home(update, ctx)


async def do_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            await _users.set_paused(u["id"], False)
    await show_home(update, ctx)


async def _auto_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "quick_start":
        await show_quick_start(update, ctx); return
    if screen == "status":
        await show_strategy_status(update, ctx); return
    if screen == "configure":
        sub = parts[2] if len(parts) > 2 else None
        if sub is None:
            await show_configure_root(update, ctx); return
        if sub == "strategy":
            arg = parts[3] if len(parts) > 3 else None
            if arg:
                _flow(ctx)["strategy"] = {
                    "momentum": "⚡ Momentum",
                    "mean_reversion": "📊 Mean Reversion",
                    "smart_hybrid": "🧪 Smart Hybrid",
                }.get(arg, "⚡ Momentum")
                await show_configure_capital(update, ctx); return
            await show_configure_root(update, ctx); return
        if sub == "capital":
            arg = parts[3] if len(parts) > 3 else None
            if arg and arg.isdigit():
                _flow(ctx)["capital"] = float(arg)
                await show_configure_risk(update, ctx); return
            await show_configure_capital(update, ctx); return
        if sub == "risk":
            arg = parts[3] if len(parts) > 3 else None
            if arg:
                _flow(ctx)["risk"] = {
                    "safe": "🟢 Safe",
                    "balanced": "🟡 Balanced",
                    "aggressive": "🔴 Aggressive",
                }.get(arg, "🟡 Balanced")
                await show_configure_review(update, ctx); return
            await show_configure_risk(update, ctx); return
        if sub == "review":
            await show_configure_review(update, ctx); return
    if screen == "start":
        await do_start(update, ctx); return
    if screen == "pause":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "confirm":
            await do_pause(update, ctx); return
        await show_pause_confirm(update, ctx); return
    if screen == "resume":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "confirm":
            await do_resume(update, ctx); return
        await show_resume_confirm(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_auto_cb, pattern=r"^auto:"))
