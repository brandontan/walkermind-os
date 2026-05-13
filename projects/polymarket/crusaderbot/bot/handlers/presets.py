"""Strategy preset system handlers (Phase 5C).

Replaces the raw strategy / risk / capital / TP-SL multi-step picker with a
named-preset flow:

    Preset Picker  →  Confirmation Card  →  Activate
                                            └── Status Card (Edit / Switch / Pause / Stop)

Activation only writes config + flips ``users.auto_trade_on`` while the
trading mode is *paper*. Live activation continues to require the existing
2FA-gated dashboard toggle so this lane changes zero activation guards.
"""
from __future__ import annotations

import logging
from typing import Tuple

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, filters,
)

from ...database import get_pool
from ...domain.preset import Preset, get_preset, list_presets
from ...users import (
    get_settings_for, set_auto_trade, set_paused, update_settings, upsert_user,
)
from ...wallet.ledger import daily_pnl, get_balance
from ..keyboards import mvp_auto_trade_kb
from ..keyboards.presets import (
    preset_confirm, preset_picker, preset_status, preset_stop_confirm,
    preset_switch_confirm,
    wizard_capital_kb, wizard_custom_input_kb, wizard_done_kb,
    wizard_review_kb, wizard_sl_kb, wizard_tp_kb,
)
from ..tier import Tier, has_tier, tier_block_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier gate — preset activation is configuration only, so allowlist (Tier 2)
# is enough. Live trading still requires the dashboard toggle's full gate.
# ---------------------------------------------------------------------------

async def _ensure_tier2(update: Update) -> Tuple[dict | None, bool]:
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


async def _reply(update: Update, text: str, **kw) -> None:
    """Reply via message or callback, whichever surface is active."""
    if update.message is not None:
        await update.message.reply_text(text, **kw)
    elif update.callback_query is not None and update.callback_query.message is not None:
        await update.callback_query.message.reply_text(text, **kw)


# ---------------------------------------------------------------------------
# Card renderers
# ---------------------------------------------------------------------------

# Maps internal preset key → MVP display label
_MVP_LABELS: dict[str, tuple[str, str]] = {
    "signal_sniper": ("📡", "Conservative"),
    "value_hunter":  ("🎯", "Balanced"),
    "full_auto":     ("🚀", "Aggressive"),
}

_MVP_DESCRIPTIONS: dict[str, str] = {
    "signal_sniper": "Lower risk, fewer trades",
    "value_hunter":  "Recommended for most users",
    "full_auto":     "Higher frequency, higher risk",
}


def _preset_picker_text(active_preset_key: str | None = None) -> str:
    """MVP Auto Trade screen — simple Conservative/Balanced/Aggressive."""
    strategy_line = "Not selected"
    if active_preset_key and active_preset_key in _MVP_LABELS:
        emoji, label = _MVP_LABELS[active_preset_key]
        strategy_line = f"{emoji} {label}"
    return (
        "🤖 Auto Trade\n"
        "\n"
        "Status\n"
        "└ 🟢 Ready\n"
        "\n"
        "Strategy\n"
        f"└ {strategy_line}\n"
        "\n"
        "Choose trading style:"
    )


def _preset_confirm_text(p: Preset) -> str:
    """MVP confirmation card — uses simplified labels."""
    mvp_emoji, mvp_label = _MVP_LABELS.get(p.key, (p.emoji, p.name))
    mvp_desc = _MVP_DESCRIPTIONS.get(p.key, "")
    return (
        f"🤖 Auto Trade / {mvp_emoji} {mvp_label}\n"
        "\n"
        "Strategy\n"
        f"├ Style: {mvp_label}\n"
        f"└ {mvp_desc}\n"
        "\n"
        "Configuration\n"
        f"├ Capital: {p.capital_pct * 100:.0f}% of balance\n"
        f"├ Take Profit: +{p.tp_pct * 100:.0f}%\n"
        f"├ Stop Loss: -{p.sl_pct * 100:.0f}%\n"
        f"└ Max Size: {p.max_position_pct * 100:.0f}% per trade\n"
        "\n"
        "Mode\n"
        "└ 📑 Paper\n"
        "\n"
        "Looks good?"
    )


async def _preset_status_text(user: dict, p: Preset) -> str:
    bal = await get_balance(user["id"])
    pnl = await daily_pnl(user["id"])
    pool = get_pool()
    async with pool.acquire() as conn:
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM positions "
            "WHERE user_id=$1 AND status='open'",
            user["id"],
        )
    auto_on = bool(user["auto_trade_on"])
    paused = bool(user.get("paused"))
    if not auto_on:
        state = "🔴 Disabled"
    elif paused:
        state = "⏸ Paused"
    else:
        state = "🟢 Running"
    pnl_icon = "📈" if float(pnl) >= 0 else "📉"
    return (
        "📊 Auto Trade Status\n"
        "\n"
        "Strategy\n"
        f"├ {p.emoji} {p.name}\n"
        f"└ State: {state}\n"
        "\n"
        "Performance\n"
        f"├ Balance: ${float(bal):.2f} USDC\n"
        f"├ Today P&L: {pnl_icon} ${float(pnl):+.2f}\n"
        f"└ Positions: {int(open_count)} open\n"
        "\n"
        "Config\n"
        f"├ Capital: {p.capital_pct * 100:.0f}%\n"
        f"├ TP / SL: +{p.tp_pct * 100:.0f}% / -{p.sl_pct * 100:.0f}%\n"
        "└ Mode: 📝 Paper"
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

async def show_preset_picker(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the MVP Auto Trade screen."""
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    if ctx.user_data:
        ctx.user_data.pop("awaiting", None)
    s = await get_settings_for(user["id"])
    active_preset = s.get("active_preset")
    await _reply(
        update, _preset_picker_text(active_preset),
        reply_markup=mvp_auto_trade_kb(),
    )


async def show_preset_status(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the status card for the user's active preset.

    Falls back to the picker if the user has no active preset.
    """
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    s = await get_settings_for(user["id"])
    preset_key = s.get("active_preset")
    p = get_preset(preset_key) if preset_key else None
    if p is None:
        await show_preset_picker(update, ctx)
        return
    text = await _preset_status_text(user, p)
    await _reply(
        update, text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=preset_status(paused=bool(user.get("paused"))),
    )


# ---------------------------------------------------------------------------
# Callback dispatcher (CallbackQueryHandler pattern: ^preset:)
# ---------------------------------------------------------------------------

async def preset_callback(update: Update,
                          ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    parts = (q.data or "").split(":")
    # parts[0] == 'preset', parts[1] == action, parts[2:] action-args
    if len(parts) < 2:
        return
    action = parts[1]
    arg = parts[2] if len(parts) > 2 else ""

    if action == "picker":
        await show_preset_picker(update, ctx)
        return
    if action == "status":
        await show_preset_status(update, ctx)
        return
    if action == "pick":
        await _on_pick(update, arg)
        return
    if action == "activate":
        await _on_activate(update, ctx, user, arg)
        return
    if action == "customize":
        await _on_customize(update)
        return
    if action == "edit":
        await _on_edit(update)
        return
    if action == "switch":
        await _reply(
            update,
            "Switching deactivates the current preset before you pick a new one.",
            reply_markup=preset_switch_confirm(),
        )
        return
    if action == "switch_yes":
        await _on_switch_yes(update, ctx, user)
        return
    if action == "pause":
        await _on_pause(update, user, paused=True)
        return
    if action == "resume":
        await _on_pause(update, user, paused=False)
        return
    if action == "stop":
        await _reply(
            update,
            "Stop turns auto-trade OFF and clears the active preset. "
            "Open positions are not closed.",
            reply_markup=preset_stop_confirm(),
        )
        return
    if action == "stop_yes":
        await _on_stop_yes(update, ctx, user)
        return


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

async def _on_pick(update: Update, preset_key: str) -> None:
    p = get_preset(preset_key)
    if p is None:
        await _reply(update, "❌ Unknown preset.")
        return
    await _reply(
        update, _preset_confirm_text(p),
        parse_mode=ParseMode.MARKDOWN, reply_markup=preset_confirm(p.key),
    )


async def _on_activate(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                       user: dict, preset_key: str) -> None:
    if user.get("locked", False):
        await _reply(update, "🔒 Account locked. Contact an operator to unlock.")
        return
    p = get_preset(preset_key)
    if p is None:
        await _reply(update, "❌ Unknown preset.")
        return
    s = await get_settings_for(user["id"])
    # Live mode requires the existing 2FA-gated dashboard activation flow.
    # The preset surface stays paper-only so we never bypass an activation
    # guard that the dashboard toggle already enforces.
    if s.get("trading_mode") == "live":
        await _reply(
            update,
            "⚠️ Live trading is active. Live preset activation is not yet "
            "supported — switch to paper mode in /settings, or use the "
            "Dashboard auto-trade toggle which runs the live activation "
            "checklist.",
        )
        return
    await update_settings(
        user["id"],
        active_preset=p.key,
        strategy_types=list(p.strategies),
        capital_alloc_pct=p.capital_pct,
        tp_pct=p.tp_pct,
        sl_pct=p.sl_pct,
        max_position_pct=p.max_position_pct,
    )
    await set_auto_trade(user["id"], True)
    await set_paused(user["id"], False)
    logger.info(
        "preset.activate user=%s preset=%s strategies=%s",
        user["id"], p.key, list(p.strategies),
    )
    # Reload the user row so the status card reflects the freshly flipped
    # auto_trade_on / paused fields instead of the stale snapshot.
    refreshed = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    text = (
        f"✅ *{p.emoji} {p.name}* activated.\n"
        f"Auto-trade is now *ON* (paper mode).\n\n"
        + await _preset_status_text(refreshed, p)
    )
    await _reply(
        update, text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=preset_status(paused=False),
    )


async def _on_customize(update: Update) -> None:
    await _reply(
        update,
        "✏️ Customize wizard ships in Phase 5G. For now the preset values "
        "are activated as-is.",
    )


async def _on_edit(update: Update) -> None:
    await _reply(
        update,
        "✏️ Inline edit ships in Phase 5G. To change settings now, *Switch* "
        "to a different preset or *Stop* and re-pick.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _on_switch_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                         user: dict) -> None:
    await update_settings(
        user["id"],
        active_preset=None,
        max_position_pct=None,
    )
    await set_auto_trade(user["id"], False)
    await set_paused(user["id"], False)
    logger.info("preset.switch user=%s cleared", user["id"])
    await show_preset_picker(update, ctx)


async def _on_pause(update: Update, user: dict, *, paused: bool) -> None:
    if not paused and user.get("locked", False):
        await _reply(update, "🔒 Account locked. Contact an operator to unlock.")
        return
    await set_paused(user["id"], paused)
    logger.info("preset.pause user=%s paused=%s", user["id"], paused)
    s = await get_settings_for(user["id"])
    p = get_preset(s.get("active_preset")) if s.get("active_preset") else None
    if p is None:
        await _reply(update, "No active preset.")
        return
    refreshed = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    state_word = "paused" if paused else "resumed"
    text = (f"{'⏸' if paused else '▶️'} Auto-trade {state_word}.\n\n"
            + await _preset_status_text(refreshed, p))
    await _reply(
        update, text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=preset_status(paused=paused),
    )


async def _on_stop_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                       user: dict) -> None:
    await update_settings(
        user["id"],
        active_preset=None,
        max_position_pct=None,
    )
    await set_auto_trade(user["id"], False)
    await set_paused(user["id"], False)
    logger.info("preset.stop user=%s", user["id"])
    await _reply(
        update,
        "🛑 Auto-trade stopped. Active preset cleared. Open positions are "
        "untouched — close them via /positions if needed.",
    )


# ===========================================================================
# Phase 5G — Customize wizard ConversationHandler
# ===========================================================================

# Conversation state tokens
CUSTOM_CAPITAL = 0
CUSTOM_TP = 1
CUSTOM_SL = 2
CUSTOM_REVIEW = 3
CUSTOM_INPUT = 4

# MVP Reset V1 — Signal Feeds and Insights removed from main navigation
_MENU_BUTTONS_CUSTOMIZE = {
    "🏠 Dashboard", "💼 Portfolio", "🤖 Auto Trade",
    "⚙️ Settings", "🛑 Stop Bot",
}


def _cwz(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    return ctx.user_data.setdefault("customize_wz", {})


# ---------------------------------------------------------------------------
# Text renderers
# ---------------------------------------------------------------------------

def _step1_text(p: Preset) -> str:
    return (
        "🤖 Auto Trade / Configure / Capital\n"
        "\n"
        "Preset\n"
        f"└ {p.emoji} {p.name}\n"
        "\n"
        "Choose capital allocation:"
    )


def _step2_text() -> str:
    return (
        "🤖 Auto Trade / Configure / Take Profit\n"
        "\n"
        "Auto-close winning positions at:"
    )


def _step3_text() -> str:
    return (
        "🤖 Auto Trade / Configure / Stop Loss\n"
        "\n"
        "Auto-close losing positions at:"
    )


def _step5_text(wz: dict, p: Preset) -> str:
    cap = round(wz["capital_pct"] * 100)
    tp = round(wz["tp_pct"] * 100)
    sl = round(wz["sl_pct"] * 100)
    return (
        "🤖 Auto Trade / Configure / Review\n"
        "\n"
        "Preset\n"
        f"└ {p.emoji} {p.name}\n"
        "\n"
        "Configuration\n"
        f"├ Capital: {cap}%\n"
        f"├ Take Profit: +{tp}%\n"
        f"├ Stop Loss: -{sl}%\n"
        "└ Mode: 📝 Paper\n"
        "\n"
        "Looks good?"
    )


# ---------------------------------------------------------------------------
# Entry handlers
# ---------------------------------------------------------------------------

async def wizard_enter_customize(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Entry: user tapped Customize on the confirmation card."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return ConversationHandler.END

    preset_key = (q.data or "")[len("preset:customize:"):]
    p = get_preset(preset_key)
    if p is None:
        if q.message:
            await q.message.reply_text("❌ Unknown preset.")
        return ConversationHandler.END

    ctx.user_data["customize_wz"] = {
        "preset_key": preset_key,
        "is_new_activation": True,
        "capital_pct": p.capital_pct,
        "tp_pct": p.tp_pct,
        "sl_pct": p.sl_pct,
        "custom_field": None,
    }
    if q.message:
        await q.message.edit_text(
            _step1_text(p),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_capital_kb(),
        )
    return CUSTOM_CAPITAL


async def wizard_enter_edit(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Entry: user tapped Edit Config on the status card."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return ConversationHandler.END

    s = await get_settings_for(user["id"])
    preset_key = s.get("active_preset")
    p = get_preset(preset_key) if preset_key else None
    if p is None:
        if q.message:
            await q.message.reply_text("No active preset to edit.")
        return ConversationHandler.END

    ctx.user_data["customize_wz"] = {
        "preset_key": preset_key,
        "is_new_activation": False,
        "capital_pct": float(s.get("capital_alloc_pct") or p.capital_pct),
        "tp_pct": float(s.get("tp_pct") or p.tp_pct),
        "sl_pct": float(s.get("sl_pct") or p.sl_pct),
        "custom_field": None,
    }
    if q.message:
        await q.message.edit_text(
            _step1_text(p),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_capital_kb(),
        )
    return CUSTOM_CAPITAL


# ---------------------------------------------------------------------------
# Step 1 — Capital
# ---------------------------------------------------------------------------

async def step1_capital_select(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_CAPITAL
    await q.answer()
    pct_str = (q.data or "")[len("customize:capital:"):]
    try:
        pct = int(pct_str) / 100.0
    except ValueError:
        return CUSTOM_CAPITAL
    _cwz(ctx)["capital_pct"] = pct
    if q.message:
        await q.message.edit_text(
            _step2_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_tp_kb(),
        )
    return CUSTOM_TP


# ---------------------------------------------------------------------------
# Step 2 — Take Profit
# ---------------------------------------------------------------------------

async def step2_tp_select(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_TP
    await q.answer()
    pct_str = (q.data or "")[len("customize:tp:"):]
    try:
        pct = int(pct_str) / 100.0
    except ValueError:
        return CUSTOM_TP
    _cwz(ctx)["tp_pct"] = pct
    if q.message:
        await q.message.edit_text(
            _step3_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_sl_kb(),
        )
    return CUSTOM_SL


async def step2_tp_custom(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_TP
    await q.answer()
    _cwz(ctx)["custom_field"] = "tp"
    if q.message:
        await q.message.edit_text(
            "*Take Profit — Custom Value*\n\n"
            "Enter a number between 1 and 200 (e.g. `25` for +25%):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_custom_input_kb("tp"),
        )
    return CUSTOM_INPUT


# ---------------------------------------------------------------------------
# Step 3 — Stop Loss
# ---------------------------------------------------------------------------

async def step3_sl_select(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_SL
    await q.answer()
    pct_str = (q.data or "")[len("customize:sl:"):]
    try:
        pct = int(pct_str) / 100.0
    except ValueError:
        return CUSTOM_SL
    wz = _cwz(ctx)
    wz["sl_pct"] = pct
    p = get_preset(wz.get("preset_key", ""))
    if q.message:
        await q.message.edit_text(
            _step5_text(wz, p) if p else "*Step 5/5 — Review*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_review_kb(),
        )
    return CUSTOM_REVIEW


async def step3_sl_custom(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_SL
    await q.answer()
    _cwz(ctx)["custom_field"] = "sl"
    if q.message:
        await q.message.edit_text(
            "*Stop Loss — Custom Value*\n\n"
            "Enter a number between 1 and 50 (e.g. `12` for -12%):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_custom_input_kb("sl"),
        )
    return CUSTOM_INPUT


# ---------------------------------------------------------------------------
# Custom text input (shared TP / SL)
# ---------------------------------------------------------------------------

async def custom_input_handler(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.message is None:
        return CUSTOM_INPUT
    raw = (update.message.text or "").strip()

    # Menu tap exits wizard immediately.
    if raw in _MENU_BUTTONS_CUSTOMIZE:
        ctx.user_data.pop("customize_wz", None)
        return ConversationHandler.END

    wz = _cwz(ctx)
    field = wz.get("custom_field")

    try:
        value = float(raw)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please enter a number (e.g. `15` for 15%).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return CUSTOM_INPUT

    if field == "tp":
        if not (1 <= value <= 200):
            await update.message.reply_text(
                "⚠️ Take Profit must be between 1 and 200.",
            )
            return CUSTOM_INPUT
        wz["tp_pct"] = value / 100.0
        wz["custom_field"] = None
        await update.message.reply_text(
            _step3_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_sl_kb(),
        )
        return CUSTOM_SL

    if field == "sl":
        if not (1 <= value <= 50):
            await update.message.reply_text(
                "⚠️ Stop Loss must be between 1 and 50.",
            )
            return CUSTOM_INPUT
        wz["sl_pct"] = value / 100.0
        wz["custom_field"] = None
        p = get_preset(wz.get("preset_key", ""))
        await update.message.reply_text(
            _step5_text(wz, p) if p else "*Step 5/5 — Review*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_review_kb(),
        )
        return CUSTOM_REVIEW

    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Step 5 — Save
# ---------------------------------------------------------------------------

async def step_save(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_REVIEW
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return ConversationHandler.END

    wz = _cwz(ctx)
    preset_key = wz.get("preset_key")
    p = get_preset(preset_key) if preset_key else None
    if p is None:
        if q.message:
            await q.message.reply_text("❌ Preset not found.")
        return ConversationHandler.END

    if wz.get("is_new_activation"):
        if user.get("locked", False):
            if q.message:
                await q.message.reply_text(
                    "🔒 Account locked. Contact an operator to unlock.",
                )
            return ConversationHandler.END
        s = await get_settings_for(user["id"])
        if s.get("trading_mode") == "live":
            if q.message:
                await q.message.reply_text(
                    "⚠️ Live trading is active. Live preset activation is not yet "
                    "supported — switch to paper mode in /settings, or use the "
                    "Dashboard auto-trade toggle which runs the live activation "
                    "checklist.",
                )
            return ConversationHandler.END
        await update_settings(
            user["id"],
            active_preset=p.key,
            strategy_types=list(p.strategies),
            capital_alloc_pct=wz["capital_pct"],
            tp_pct=wz["tp_pct"],
            sl_pct=wz["sl_pct"],
            max_position_pct=p.max_position_pct,
        )
        await set_auto_trade(user["id"], True)
        await set_paused(user["id"], False)
    else:
        await update_settings(
            user["id"],
            capital_alloc_pct=wz["capital_pct"],
            tp_pct=wz["tp_pct"],
            sl_pct=wz["sl_pct"],
        )

    logger.info(
        "customize.save user=%s preset=%s capital=%.2f tp=%.2f sl=%.2f new=%s",
        user["id"], p.key,
        wz["capital_pct"], wz["tp_pct"], wz["sl_pct"],
        wz.get("is_new_activation"),
    )
    ctx.user_data.pop("customize_wz", None)

    if q.message:
        await q.message.edit_text(
            "✅ Settings saved. Auto-Trade will use your custom config.",
            reply_markup=wizard_done_kb(),
        )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Back navigation
# ---------------------------------------------------------------------------

async def step_back_to_capital(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_CAPITAL
    await q.answer()
    wz = _cwz(ctx)
    p = get_preset(wz.get("preset_key", ""))
    if q.message:
        await q.message.edit_text(
            _step1_text(p) if p else "*Step 1/5 — Capital Allocation*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_capital_kb(),
        )
    return CUSTOM_CAPITAL


async def step_back_to_tp(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_TP
    await q.answer()
    if q.message:
        await q.message.edit_text(
            _step2_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_tp_kb(),
        )
    return CUSTOM_TP


async def step_back_to_sl(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return CUSTOM_SL
    await q.answer()
    if q.message:
        await q.message.edit_text(
            _step3_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_sl_kb(),
        )
    return CUSTOM_SL


# ---------------------------------------------------------------------------
# Cancel / fallbacks
# ---------------------------------------------------------------------------

async def wizard_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()
    ctx.user_data.pop("customize_wz", None)
    if q.message:
        await q.message.edit_text(
            "✕ Customize cancelled. Original preset settings kept.",
        )
    return ConversationHandler.END


async def wizard_fallback_menu(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    from .onboarding import menu_handler as _menu_handler
    ctx.user_data.pop("customize_wz", None)
    await _menu_handler(update, ctx)
    return ConversationHandler.END


async def wizard_menu_tap(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    from ..menus.main import get_menu_route
    ctx.user_data.pop("customize_wz", None)
    text = (update.message.text or "").strip() if update.message else ""
    handler = get_menu_route(text)
    if handler:
        await handler(update, ctx)
    return ConversationHandler.END


async def wizard_fallback_text(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.message:
        await update.message.reply_text("Tap a button or /menu to exit.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ConversationHandler factory
# ---------------------------------------------------------------------------

def build_customize_handler() -> ConversationHandler:
    """Return the Phase 5G customize wizard ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                wizard_enter_customize, pattern=r"^preset:customize:",
            ),
            CallbackQueryHandler(
                wizard_enter_edit, pattern=r"^preset:edit$",
            ),
        ],
        states={
            CUSTOM_CAPITAL: [
                CallbackQueryHandler(
                    step1_capital_select, pattern=r"^customize:capital:\d+$",
                ),
                CallbackQueryHandler(wizard_cancel, pattern=r"^customize:cancel$"),
            ],
            CUSTOM_TP: [
                CallbackQueryHandler(
                    step2_tp_select, pattern=r"^customize:tp:\d+$",
                ),
                CallbackQueryHandler(
                    step2_tp_custom, pattern=r"^customize:tp:custom$",
                ),
                CallbackQueryHandler(
                    step_back_to_capital, pattern=r"^customize:back:capital$",
                ),
                CallbackQueryHandler(wizard_cancel, pattern=r"^customize:cancel$"),
            ],
            CUSTOM_SL: [
                CallbackQueryHandler(
                    step3_sl_select, pattern=r"^customize:sl:\d+$",
                ),
                CallbackQueryHandler(
                    step3_sl_custom, pattern=r"^customize:sl:custom$",
                ),
                CallbackQueryHandler(
                    step_back_to_tp, pattern=r"^customize:back:tp$",
                ),
                CallbackQueryHandler(wizard_cancel, pattern=r"^customize:cancel$"),
            ],
            CUSTOM_REVIEW: [
                CallbackQueryHandler(step_save,       pattern=r"^customize:save$"),
                CallbackQueryHandler(
                    step_back_to_sl, pattern=r"^customize:back:sl$",
                ),
                CallbackQueryHandler(wizard_cancel, pattern=r"^customize:cancel$"),
            ],
            CUSTOM_INPUT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, custom_input_handler,
                ),
                CallbackQueryHandler(
                    step_back_to_tp, pattern=r"^customize:back:tp$",
                ),
                CallbackQueryHandler(
                    step_back_to_sl, pattern=r"^customize:back:sl$",
                ),
                CallbackQueryHandler(wizard_cancel, pattern=r"^customize:cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("menu", wizard_fallback_menu),
            MessageHandler(
                filters.Regex(r"^(📊|🐋|🤖|📈|⚙️|🛑)"), wizard_menu_tap,
            ),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, wizard_fallback_text,
            ),
        ],
        per_message=False,
        allow_reentry=True,
        name="customize_wizard",
    )
