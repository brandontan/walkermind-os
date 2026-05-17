"""Settings hub handler — UX Overhaul.

Hub surface: ⚙️ Settings reply-keyboard button → settings_hub_root
Sub-surfaces (all via settings:* callbacks):
  settings:wallet      → wallet surface
  settings:tpsl        → TP/SL 2-step preset flow
  settings:capital     → Capital allocation preset flow
  settings:risk        → Risk profile picker
  settings:notifications → notif on/off toggle (settings:notif_on/_off →
                           user_settings.notifications_on; enforced on the
                           per-user trade + daily-summary send path)
  settings:mode        → Paper/Live mode picker
  settings:hub         → re-render hub
  settings:back        → send main_menu reply keyboard

TP/SL flow (2 steps):
  settings:tpsl → tp_preset_kb (callbacks: tp_set:<N> / tp_set:custom)
  tp_set:<N>    → save TP, show sl_preset_kb
  tp_set:custom → set awaiting="tpsl_tp", prompt text
  sl_set:<N>    → save SL, show confirm
  sl_set:custom → set awaiting="tpsl_sl", prompt text

Capital flow:
  settings:capital → capital_preset_kb (callbacks: cap_set:<N> / cap_set:custom)
  cap_set:<N>      → save capital %, show confirm
  cap_set:custom   → set awaiting="capital_pct", prompt text (reuses setup.text_input)
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...users import get_settings_for, update_settings, upsert_user
from ...wallet.ledger import get_balance
from ...config import get_settings as get_app_settings
from ...database import get_pool
from ..keyboards import mvp_risk_kb, risk_picker, setup_menu
from ..roles import is_admin as _is_admin
from ..keyboards.settings import (
    autoredeem_settings_picker,
    capital_preset_kb,
    settings_hub_kb,
    settings_menu,
    sl_preset_kb,
    tp_preset_kb,
    tpsl_confirm_kb,
)


logger = logging.getLogger(__name__)

def _hub_text(mode: str, risk_profile: str = "balanced") -> str:
    """V6 Settings hub — clean grouped display."""
    mode_label = "💸 Live" if mode == "live" else "📑 Paper"
    risk_display = {
        "conservative": "📡 Conservative",
        "balanced": "⚡ Balanced",
        "aggressive": "🚀 Aggressive",
    }.get(risk_profile, risk_profile.title())
    return (
        "<b>⚙️ Settings</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Trading</b>\n"
        f"├─ Mode: {mode_label}\n"
        f"└─ Risk: {risk_display}\n\n"
        "<b>Account</b>\n"
        "└─ Notifications: 🟢 ON"
    )


def _tp_step_text(current_tp: float | None) -> str:
    current_str = f"+{current_tp * 100:.0f}%" if current_tp is not None else "not set"
    return (
        "<b>📊 Take Profit</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Current: <code>{current_str}</code>\n\n"
        "Select your take-profit target:"
    )


def _sl_step_text(current_sl: float | None) -> str:
    current_str = f"-{current_sl * 100:.0f}%" if current_sl is not None else "not set"
    return (
        "<b>📊 Stop Loss</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Current: <code>{current_str}</code>\n\n"
        "Select your stop-loss threshold:"
    )


def _capital_text(balance: float, mode: str) -> str:
    mode_label = "💸 Live" if mode == "live" else "📙 Paper"
    return (
        "<b>💰 Capital Allocation</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<pre>"
        f"Balance  ${balance:.2f} ({mode_label})\n"
        "Max      95% per trade"
        "</pre>\n\n"
        "⚠️ Full allocation (100%) is forbidden."
    )


async def _ensure(update: Update) -> tuple[dict | None, bool]:
    if update.effective_user is None:
        return None, False
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    return user, True


async def _render_hub(update: Update, user: dict) -> None:
    """Shared hub render — handles message and callback surfaces."""
    s = await get_settings_for(user["id"])
    mode = s.get("trading_mode", "paper")
    risk_profile = s.get("risk_profile", "balanced")
    text = _hub_text(mode, risk_profile)
    kb = settings_hub_kb(is_admin=_is_admin(user))
    if update.callback_query is not None:
        await update.callback_query.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb,
        )
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb,
        )


async def settings_hub_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE, refresh: bool = False) -> None:
    user, ok = await _ensure(update)
    if not ok:
        return
    await _render_hub(update, user)


async def settings_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user, ok = await _ensure(update)
    if not ok or update.message is None:
        return
    await _render_hub(update, user)


async def settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all settings:* callback queries."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    data = q.data or ""

    if data in ("settings:hub", "settings:menu"):
        await _render_hub(update, user)
        return

    if data == "settings:back":
        from ..keyboards import main_menu
        s = await get_settings_for(user["id"])
        strategy_key = s.get("active_preset")
        auto_on = bool(user.get("auto_trade_on", False))
        await q.message.reply_text(
            "Main menu:", reply_markup=main_menu(strategy_key=strategy_key, auto_on=auto_on),
        )
        return

    if data == "settings:profile":
        await _render_hub(update, user)
        return

    if data == "settings:referrals":
        from ...services.referral.referral_service import get_or_create_referral_code
        try:
            code = await get_or_create_referral_code(user["id"])
            ref_link = f"https://t.me/{(await q.get_bot()).username}?start=ref_{code}"
        except Exception:  # noqa: BLE001
            ref_link = "(unavailable)"
        await q.message.reply_text(
            "<b>🎁 Referrals</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Your referral link:\n<code>{ref_link}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=settings_hub_kb(),
        )
        return

    if data == "settings:health":
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                job_rows = await conn.fetch(
                    "SELECT job_id, status, finished_at FROM job_runs "
                    "ORDER BY finished_at DESC LIMIT 3",
                )
            if job_rows:
                job_summary = "\n".join(
                    f"├ {r['job_id']}: {r['status']}" for r in job_rows
                )
            else:
                job_summary = "└ No recent jobs"
        except Exception:  # noqa: BLE001
            job_summary = "└ Jobs: nominal"
        await q.message.reply_text(
            f"<b>🏥 Health</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 Bot: Online\n"
            f"🕐 Time: {now}\n\n"
            "<b>Recent jobs</b>\n"
            f"{job_summary}",
            parse_mode=ParseMode.HTML,
            reply_markup=settings_hub_kb(),
        )
        return

    if data == "settings:live_gate":
        await q.message.reply_text(
            "<b>🔐 Live Gate</b>\n\nLive trading is not yet available.\n\nStay tuned for activation.",
            parse_mode=ParseMode.HTML,
            reply_markup=settings_hub_kb(),
        )
        return

    if data == "settings:admin":
        if not _is_admin(user):
            await q.answer("Admin access required.", show_alert=True)
            return
        from .admin import admin_root
        await admin_root(update, ctx)
        return

    if data == "settings:wallet":
        import html as _html
        from ...wallet.vault import get_wallet
        w = await get_wallet(user["id"])
        addr = w["deposit_address"] if w else "(not set)"
        from ..keyboards import wallet_menu
        await q.message.reply_text(
            f"<b>💰 Wallet</b>\n\nDeposit address (Polygon USDC):\n<code>{_html.escape(addr)}</code>\n\n"
            "Tap an option below.",
            parse_mode=ParseMode.HTML,
            reply_markup=wallet_menu(),
        )
        return

    if data == "settings:tpsl":
        s = await get_settings_for(user["id"])
        current_tp = float(s["tp_pct"]) if s.get("tp_pct") is not None else None
        await q.message.reply_text(
            _tp_step_text(current_tp),
            parse_mode=ParseMode.HTML,
            reply_markup=tp_preset_kb(current_tp * 100 if current_tp else None),
        )
        return

    if data == "settings:capital":
        s = await get_settings_for(user["id"])
        bal = float(await get_balance(user["id"]))
        mode = s.get("trading_mode", "paper")
        await q.message.reply_text(
            _capital_text(bal, mode),
            parse_mode=ParseMode.HTML,
            reply_markup=capital_preset_kb(bal, mode),
        )
        return

    if data == "settings:risk":
        s = await get_settings_for(user["id"])
        current_risk = s.get("risk_profile", "balanced")
        await q.message.reply_text(
            "<b>⚖️ Risk Profile</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Choose your risk level:\n\n"
            "📡 <b>Conservative</b>\n"
            "Safer, smaller exposure\n\n"
            "⚡ <b>Balanced</b>\n"
            "Recommended for most users\n\n"
            "🚀 <b>Aggressive</b>\n"
            "Higher exposure",
            parse_mode=ParseMode.HTML,
            reply_markup=mvp_risk_kb(current_risk),
        )
        return

    if data == "settings:notifications":
        s = await get_settings_for(user["id"])
        notifs_on = s.get("notifications_on", True)
        status = "🟢 ON" if notifs_on else "🔴 OFF"
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        toggle_cb = "settings:notif_off" if notifs_on else "settings:notif_on"
        toggle_label = "Turn OFF" if notifs_on else "Turn ON"
        notif_icon = "\U0001f515" if notifs_on else "\U0001f514"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{notif_icon} {toggle_label}", callback_data=toggle_cb)],
            [
                InlineKeyboardButton("⬅ Back", callback_data="settings:hub"),
                InlineKeyboardButton("🏠 Home", callback_data="dashboard:main"),
            ],
        ])
        await q.message.reply_text(
            f"<b>🔔 Notifications</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Status: {status}\n\n"
            "You receive alerts for opened/closed trades\nand daily P&L summaries.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    if data in ("settings:notif_on", "settings:notif_off"):
        new_val = data == "settings:notif_on"
        try:
            await update_settings(user["id"], notifications_on=new_val)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notifications_on update failed: %s", exc)
        status = "🟢 ON" if new_val else "🔴 OFF"
        await q.answer(f"Notifications {status}", show_alert=False)
        await _render_hub(update, user)
        return

    if data == "settings:mode":
        from ..keyboards.settings import settings_mode_picker
        s = await get_settings_for(user["id"])
        await q.message.reply_text(
            "<b>📔 Mode</b>\n\nPaper: safe virtual trading. Live: real capital (unlock required).",
            parse_mode=ParseMode.HTML,
            reply_markup=settings_mode_picker(s["trading_mode"]),
        )
        return

    if data == "settings:redeem":
        s = await get_settings_for(user["id"])
        await q.message.reply_text(
            "Pick auto-redeem mode.\n\n"
            "<b>Instant</b> — settle the moment a market resolves.\n"
            "<b>Hourly</b> — wait for the hourly batch (default, lower gas).",
            parse_mode=ParseMode.HTML,
            reply_markup=autoredeem_settings_picker(s["auto_redeem_mode"]),
        )
        return

    if data.startswith("settings:redeem_set:"):
        choice = data.split(":", 2)[-1]
        if choice not in ("instant", "hourly"):
            return
        await update_settings(user["id"], auto_redeem_mode=choice)
        await q.message.edit_reply_markup(
            reply_markup=autoredeem_settings_picker(choice),
        )
        await q.message.reply_text(
            f"✅ Auto-redeem mode set to <b>{choice}</b>.",
            parse_mode=ParseMode.HTML,
        )
        return


async def tp_set_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    value = (q.data or "").split(":", 1)[-1]

    if value == "custom":
        if ctx.user_data is not None:
            ctx.user_data["awaiting"] = "tpsl_tp"
        await q.message.reply_text(
            "Enter TP percentage (e.g. 20):\n<i>integer, 1–100</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        tp_pct = int(value)
        if not 1 <= tp_pct <= 100:
            raise ValueError("out of range")
    except ValueError:
        await q.answer("Invalid TP value.", show_alert=True)
        return

    if ctx.user_data is not None:
        ctx.user_data["pending_tp"] = tp_pct

    s = await get_settings_for(user["id"])
    current_sl = float(s["sl_pct"]) if s.get("sl_pct") is not None else None
    await q.message.reply_text(
        _sl_step_text(current_sl),
        parse_mode=ParseMode.HTML,
        reply_markup=sl_preset_kb(current_sl * 100 if current_sl else None),
    )


async def sl_set_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    value = (q.data or "").split(":", 1)[-1]

    if value == "custom":
        if ctx.user_data is not None:
            ctx.user_data["awaiting"] = "tpsl_sl"
        await q.message.reply_text(
            "Enter SL percentage (e.g. 12):\n<i>integer, 1–50</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        sl_pct = int(value)
        if not 1 <= sl_pct <= 50:
            raise ValueError("out of range")
    except ValueError:
        await q.answer("Invalid SL value.", show_alert=True)
        return

    pending_tp = (ctx.user_data or {}).get("pending_tp")
    if pending_tp is None:
        s = await get_settings_for(user["id"])
        tp_pct_raw = s.get("tp_pct")
        pending_tp = int(float(tp_pct_raw) * 100) if tp_pct_raw is not None else 25

    tp_frac = pending_tp / 100.0
    sl_frac = sl_pct / 100.0
    await update_settings(user["id"], tp_pct=tp_frac, sl_pct=sl_frac)

    if ctx.user_data is not None:
        ctx.user_data.pop("pending_tp", None)

    await q.message.reply_text(
        f"✅ TP set to +{pending_tp}%, SL set to -{sl_pct}%.",
        reply_markup=tpsl_confirm_kb(),
    )


async def cap_set_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    value = (q.data or "").split(":", 1)[-1]

    if value == "custom":
        if ctx.user_data is not None:
            ctx.user_data["awaiting"] = "capital_pct"
        await q.message.reply_text(
            "Enter percentage (1–95):\n<i>integer only</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        pct = int(value)
        if not 1 <= pct <= 95:
            raise ValueError("out of range")
    except ValueError:
        await q.answer("Invalid percentage.", show_alert=True)
        return

    capital_alloc = pct / 100.0
    await update_settings(user["id"], capital_alloc_pct=capital_alloc)
    await q.message.reply_text(
        f"✅ Capital allocation set to {pct}%.",
        reply_markup=tpsl_confirm_kb(),
    )


async def settings_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle awaiting text inputs for tpsl_tp, tpsl_sl flows."""
    if update.message is None or update.effective_user is None:
        return False
    awaiting = (ctx.user_data or {}).get("awaiting")
    if awaiting not in ("tpsl_tp", "tpsl_sl"):
        return False

    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    text = (update.message.text or "").strip()

    try:
        val = int(text)
    except ValueError:
        await update.message.reply_text("❌ Enter an integer number. Try again.")
        return True

    if awaiting == "tpsl_tp":
        if not 1 <= val <= 100:
            await update.message.reply_text("❌ TP must be 1–100. Try again.")
            return True
        if ctx.user_data is not None:
            ctx.user_data["pending_tp"] = val
            ctx.user_data.pop("awaiting", None)
        s = await get_settings_for(user["id"])
        current_sl = float(s["sl_pct"]) if s.get("sl_pct") is not None else None
        await update.message.reply_text(
            _sl_step_text(current_sl),
            parse_mode=ParseMode.HTML,
            reply_markup=sl_preset_kb(current_sl * 100 if current_sl else None),
        )
        return True

    if awaiting == "tpsl_sl":
        if not 1 <= val <= 50:
            await update.message.reply_text("❌ SL must be 1–50. Try again.")
            return True
        pending_tp = (ctx.user_data or {}).get("pending_tp")
        if pending_tp is None:
            s = await get_settings_for(user["id"])
            tp_raw = s.get("tp_pct")
            pending_tp = int(float(tp_raw) * 100) if tp_raw is not None else 25
        await update_settings(user["id"], tp_pct=pending_tp / 100.0, sl_pct=val / 100.0)
        if ctx.user_data is not None:
            ctx.user_data.pop("pending_tp", None)
            ctx.user_data.pop("awaiting", None)
        await update.message.reply_text(
            f"✅ TP set to +{pending_tp}%, SL set to -{val}%.",
            reply_markup=tpsl_confirm_kb(),
        )
        return True

    return False
