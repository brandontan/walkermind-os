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

_RISK_CAPITAL_FRACTIONS: dict[str, float] = {
    "safe": 0.25,
    "balanced": 0.50,
    "aggressive": 0.80,
}
_DEFAULT_RISK_KEY = "balanced"
_RISK_LABELS: dict[str, str] = {
    "safe": "🟢 Safe",
    "balanced": "🟡 Balanced",
    "aggressive": "🔴 Aggressive",
}


_PRESET_TO_STRATEGY_FLAG: dict[str, str] = {
    # Maps preset key → system_settings strategy_enabled key
    "late_entry": "late_entry_v3",
    "late_entry_v3": "late_entry_v3",
    "signal": "signal_following",
    "signal_following": "signal_following",
    "copy_trade": "copy_trade",
    "copy": "copy_trade",
    "weather": "weather",
    "playbook": "playbook",
}


def _check_strategy_blocked(strategy_label: str, flags: dict) -> bool:
    """Return True if the strategy matching this label is globally disabled by admin."""
    label_lower = strategy_label.lower().replace(" ", "_").replace("-", "_")
    for preset_key, flag_key in _PRESET_TO_STRATEGY_FLAG.items():
        if preset_key in label_lower:
            return not flags.get(flag_key, True)
    return False


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
        "balance": 0.0, "mode": "paper",
        "capital": _DEFAULT_CAPITAL, "pnl_today": 0.0,
        "executions": 0, "win_rate": 0,
    }
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return state
    state["uuid"] = u["id"]
    state["paused"] = bool(u.get("paused"))
    state["running"] = bool(u.get("auto_trade_on")) and not state["paused"]
    settings = await _users.fetch_settings(u["id"])

    state["mode"] = await _users.fetch_trading_mode(u["id"])
    balance = await _users.fetch_balance(u["id"], state["mode"])
    state["balance"] = balance
    risk_raw = str(settings.get("risk_profile") or _DEFAULT_RISK_KEY).lower()
    fraction = _RISK_CAPITAL_FRACTIONS.get(risk_raw, _RISK_CAPITAL_FRACTIONS[_DEFAULT_RISK_KEY])
    state["capital"] = round(balance * fraction, 2) if balance > 0 else _DEFAULT_CAPITAL
    state["risk"] = _RISK_LABELS.get(risk_raw, _DEFAULT_RISK)

    preset = settings.get("active_preset")
    if preset:
        state["configured"] = True
        from ...presets import PRESET_CONFIG
        cfg = PRESET_CONFIG.get(preset, {})
        label = cfg.get("name") or str(preset).title().replace("_", " ")
        state["strategy"] = label
    state["pnl_today"] = await _users.fetch_daily_pnl(u["id"], state["mode"])
    state["win_rate"] = await _users.fetch_win_rate(u["id"], mode=state["mode"])
    state["executions"] = await _users.fetch_closed_trade_count(u["id"], days=1, mode=state["mode"])

    # Admin strategy flags — check if the user's active strategy is globally blocked
    try:
        from ....domain.ops.strategy_flags import get_all_flags  # type: ignore
        flags = await get_all_flags()
        state["strategy_flags"] = flags.get("strategies", {})
    except Exception as exc:  # noqa: BLE001
        log.debug("strategy_flags fetch failed: %s", exc)
        state["strategy_flags"] = {}

    return state


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ._send import nav_push
    nav_push(ctx, "auto")
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
    from ...ui.tree import LIVE, PAPER
    mode_label = LIVE if s.get("mode") == "live" else PAPER

    # Check if the user's active strategy is globally blocked by admin
    strategy_flags: dict = s.get("strategy_flags", {})
    admin_blocked = _check_strategy_blocked(s.get("strategy", ""), strategy_flags)
    effective_status = f"🚫 Admin Blocked" if admin_blocked and s["running"] else status

    text = mvp.render_autotrade_home(
        status=effective_status,
        strategy=s["strategy"],
        capital=s["capital"],
        risk=s["risk"],
        mode=mode_label,
        pnl_today=s["pnl_today"],
        executions=s["executions"],
        win_rate=s["win_rate"],
        admin_blocked=admin_blocked,
    )
    await send_or_edit(update, text, kb.home_kb(running=s["running"], paused=s["paused"]))


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
            settings = await _users.fetch_settings(u["id"])
            if (settings.get("trading_mode") or "paper") == "live":
                from ....domain.activation import live_checklist, live_mode  # type: ignore

                gate = await live_mode.evaluate_live_autotrade_start(
                    u["id"], trading_mode="live",
                )
                if not gate.allowed:
                    detail = (
                        live_checklist.render_telegram(gate.checklist)
                        if gate.reason == live_mode.REASON_LIVE_NOT_READY
                        else (
                            "🟡 <b>LIVE ENABLED / WAITING FOR DEPOSIT</b>\n\n"
                            "Deposit at least <b>$5 USDC.e</b> confirmed available "
                            "to start Auto-Trade. Current confirmed live balance: "
                            f"<code>${float(gate.live_balance_usdc):,.2f}</code>."
                        )
                    )
                    await send_or_edit(update, detail, None)
                    return
            await _users.set_paused(u["id"], False)
            await _users.set_auto_trade(u["id"], True)
            # Derive real capital from balance × risk fraction (WARP-72 fix)
            s = await _read_state(user)
            capital = s["capital"]
            risk = s["risk"]
        else:
            capital = f["capital"]
            risk = f["risk"]
    else:
        capital = f["capital"]
        risk = f["risk"]
    text = mvp.render_notif_bot_started(
        strategy=f["strategy"], capital=capital, risk=risk,
    )
    from ...keyboards.mvp._common import main_menu_kb
    # Use send_or_edit to avoid phantom "." message (WARP-72 fix)
    await send_or_edit(
        update, text,
        main_menu_kb(auto_on=True, paused=False, open_count=0, configured=True),
    )


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
            if arg == "custom":
                _flow(ctx)["step"] = "await_capital"
                await send_or_edit(
                    update,
                    "✏️ <b>Custom Capital</b>\n\nType the amount in USD (e.g. <code>150</code>):",
                    None,
                )
                return
            if arg and arg.isdigit():
                _flow(ctx)["capital"] = float(arg)
                _flow(ctx)["step"] = None
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


async def text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Capture free-form capital amount when the flow is awaiting custom input."""
    if update.message is None:
        return False
    f = ctx.user_data.get("mvp_auto_flow") if ctx.user_data else None
    if not f or f.get("step") != "await_capital":
        return False
    raw = (update.message.text or "").strip().lstrip("$").replace(",", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError("non-positive")
    except ValueError:
        await update.message.reply_text(
            "❌ <b>Invalid amount</b>\n\nEnter a positive number (e.g. <code>150</code>).",
            parse_mode="HTML",
            reply_markup=kb.configure_capital_kb(),
        )
        return True
    f["capital"] = round(amount, 2)
    f["step"] = None
    await update.message.reply_text(
        mvp.render_autotrade_configure_risk(),
        parse_mode="HTML",
        reply_markup=kb.configure_risk_kb(),
    )
    return True


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_auto_cb, pattern=r"^auto:"))
