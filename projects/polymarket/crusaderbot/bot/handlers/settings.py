"""Settings hub handler — UX Overhaul.

Hub surface: ⚙️ Settings reply-keyboard button → settings_hub_root
Sub-surfaces (all via settings:* callbacks):
  settings:wallet      → wallet surface
  settings:tpsl        → TP/SL 2-step preset flow
  settings:capital     → Capital allocation preset flow
  settings:risk        → Risk profile picker
  settings:notifications → stub (not in scope)
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
from ..keyboards import risk_picker, setup_menu
from ..keyboards.settings import (
    autoredeem_settings_picker,
    capital_preset_kb,
    settings_hub_kb,
    settings_menu,
    sl_preset_kb,
    tp_preset_kb,
    tpsl_confirm_kb,
)
from ..tier import Tier, has_tier, tier_block_message

logger = logging.getLogger(__name__)

def _hub_text(mode: str, tier: int) -> str:
    mode_label = "🔴 LIVE" if mode == "live" else "🟡 PAPER"
    tier_labels = {1: "Guest", 2: "Allowlisted", 3: "Funded", 4: "Premium"}
    tier_label = tier_labels.get(tier, f"Tier {tier}")
    return (
        "*⚙️ Settings*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👤 *Profile*\n"
        f"├── Mode: {mode_label}\n"
        f"└── Tier: {tier_label}\n\n"
        "Configure your trading preferences."
    )


def _tp_step_text(current_tp: float | None) -> str:
    current_str = f"+{current_tp * 100:.0f}%" if current_tp is not None else "not set"
    return (
        "📊 *Take Profit*\n"
        f"Current: {current_str}\n\n"
        "Select your take-profit target:"
    )


def _sl_step_text(current_sl: float | None) -> str:
    current_str = f"-{current_sl * 100:.0f}%" if current_sl is not None else "not set"
    return (
        "📊 *Stop Loss*\n"
        f"Current: {current_str}\n\n"
        "Select your stop-loss threshold:"
    )


def _capital_text(balance: float, mode: str) -> str:
    mode_label = "Live" if mode == "live" else "Paper"
    return (
        "💰 *Capital Allocation Per Trade*\n"
        "──────────────────\n"
        f"Balance: ${balance:.2f} ({mode_label})\n\n"
        "⚠️ Max 95% — full allocation forbidden."
    )


async def _ensure(update: Update) -> tuple[dict | None, bool]:
    if update.effective_user is None:
        return None, False
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    if not has_tier(user["access_tier"], Tier.ALLOWLISTED):
        msg = tier_block_message(Tier.ALLOWLISTED)
        if update.message:
            await update.message.reply_text(msg)
        elif update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        return None, False
    return user, True


async def _render_hub(update: Update, user: dict) -> None:
    """Shared hub render — handles message and callback surfaces."""
    s = await get_settings_for(user["id"])
    mode = s.get("trading_mode", "paper")
    tier = user.get("access_tier", 2)
    operator_id = get_app_settings().OPERATOR_CHAT_ID
    is_admin = (
        update.effective_user is not None
        and update.effective_user.id == operator_id
    )
    text = _hub_text(mode, tier)
    kb = settings_hub_kb(is_admin=is_admin)
    if update.callback_query is not None:
        await update.callback_query.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
        )
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
        )


async def settings_hub_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """⚙️ Settings reply-keyboard button → render Settings hub."""
    user, ok = await _ensure(update)
    if not ok:
        return
    await _render_hub(update, user)


async def settings_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/settings command — routes to hub, tier-gated same as main-menu entry."""
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

    # --- Hub re-render ---
    if data in ("settings:hub", "settings:menu"):
        await _render_hub(update, user)
        return

    # --- Back to main menu ---
    if data == "settings:back":
        from ..keyboards import main_menu
        await q.message.reply_text(
            "Main menu:", reply_markup=main_menu()
        )
        return

    # --- Profile stub ---
    if data == "settings:profile":
        s = await get_settings_for(user["id"])
        mode = s.get("trading_mode", "paper")
        tier = user.get("access_tier", 2)
        tier_labels = {1: "Guest", 2: "Allowlisted", 3: "Funded", 4: "Premium"}
        await q.message.reply_text(
            f"*👤 Profile*\n\nMode: {'🔴 LIVE' if mode == 'live' else '🟡 PAPER'}\n"
            f"Tier: {tier_labels.get(tier, f'Tier {tier}')}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_hub_kb(),
        )
        return

    # --- Premium stub ---
    if data == "settings:premium":
        await q.message.reply_text(
            "*👑 Premium*\n\nPremium features coming soon.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_hub_kb(),
        )
        return

    # --- Referrals ---
    if data == "settings:referrals":
        from .referral import referral_command
        await referral_command(update, ctx)
        return

    # --- Health ---
    if data == "settings:health":
        from .health import health_command
        await health_command(update, ctx)
        return

    # --- Live Gate ---
    if data == "settings:live_gate":
        from .live_gate import enable_live_command
        await enable_live_command(update, ctx)
        return

    # --- Admin (operator only) ---
    if data == "settings:admin":
        operator_id = get_app_settings().OPERATOR_CHAT_ID
        if update.effective_user is None or update.effective_user.id != operator_id:
            await q.answer("Admin access required.", show_alert=True)
            return
        from .admin import admin_root
        await admin_root(update, ctx)
        return

    # --- Wallet surface ---
    if data == "settings:wallet":
        from ...wallet.vault import get_wallet
        w = await get_wallet(user["id"])
        addr = w["deposit_address"] if w else "(not set)"
        from ..keyboards import wallet_menu
        await q.message.reply_text(
            f"*💰 Wallet*\n\nDeposit address (Polygon USDC):\n`{addr}`\n\n"
            "Tap an option below.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wallet_menu(),
        )
        return

    # --- TP/SL step 1 ---
    if data == "settings:tpsl":
        s = await get_settings_for(user["id"])
        current_tp = float(s["tp_pct"]) if s.get("tp_pct") is not None else None
        await q.message.reply_text(
            _tp_step_text(current_tp),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tp_preset_kb(current_tp * 100 if current_tp else None),
        )
        return

    # --- Capital allocation ---
    if data == "settings:capital":
        s = await get_settings_for(user["id"])
        bal = float(await get_balance(user["id"]))
        mode = s.get("trading_mode", "paper")
        await q.message.reply_text(
            _capital_text(bal, mode),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=capital_preset_kb(bal, mode),
        )
        return

    # --- Risk profile ---
    if data == "settings:risk":
        s = await get_settings_for(user["id"])
        await q.message.reply_text(
            "*⚖️ Risk Profile*\n\nSelect your risk level:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=risk_picker(s["risk_profile"]),
        )
        return

    # --- Notifications stub ---
    if data == "settings:notifications":
        await q.message.reply_text(
            "*🔔 Notifications*\n\nNotification preferences coming soon.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_hub_kb(),
        )
        return

    # --- Mode (Paper/Live) ---
    if data == "settings:mode":
        from ..keyboards.settings import settings_mode_picker
        s = await get_settings_for(user["id"])
        await q.message.reply_text(
            "*📄 Mode*\n\nPaper: safe virtual trading. Live: real capital (Tier 4 required).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_mode_picker(s["trading_mode"]),
        )
        return

    # --- Legacy auto-redeem ---
    if data == "settings:redeem":
        s = await get_settings_for(user["id"])
        await q.message.reply_text(
            "Pick auto-redeem mode.\n\n"
            "*Instant* — settle the moment a market resolves.\n"
            "*Hourly* — wait for the hourly batch (default, lower gas).",
            parse_mode=ParseMode.MARKDOWN,
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
            f"✅ Auto-redeem mode set to *{choice}*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return


async def tp_set_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle tp_set:<N> and tp_set:custom callbacks."""
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
            "Enter TP percentage (e.g. 20):\n_(integer, 1–100)_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        tp_pct = int(value)
        if not 1 <= tp_pct <= 100:
            raise ValueError("out of range")
    except ValueError:
        await q.answer("Invalid TP value.", show_alert=True)
        return

    # Store TP in user_data; wait for SL selection before saving to DB.
    if ctx.user_data is not None:
        ctx.user_data["pending_tp"] = tp_pct

    s = await get_settings_for(user["id"])
    current_sl = float(s["sl_pct"]) if s.get("sl_pct") is not None else None
    await q.message.reply_text(
        _sl_step_text(current_sl),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=sl_preset_kb(current_sl * 100 if current_sl else None),
    )


async def sl_set_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle sl_set:<N> and sl_set:custom callbacks."""
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
            "Enter SL percentage (e.g. 12):\n_(integer, 1–50)_",
            parse_mode=ParseMode.MARKDOWN,
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
        # SL tapped without TP step (edge case: direct deep-link)
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
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=tpsl_confirm_kb(),
    )


async def cap_set_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle cap_set:<N> and cap_set:custom callbacks."""
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
            "Enter percentage (1–95):\n_(integer only)_",
            parse_mode=ParseMode.MARKDOWN,
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
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=tpsl_confirm_kb(),
    )


async def settings_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle awaiting text inputs for tpsl_tp, tpsl_sl flows.

    Returns True if consumed. capital_pct is handled by setup.text_input.
    """
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
            parse_mode=ParseMode.MARKDOWN,
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
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tpsl_confirm_kb(),
        )
        return True

    return False
