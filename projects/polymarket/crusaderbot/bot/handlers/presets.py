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
from telegram.ext import ContextTypes

from ...database import get_pool
from ...domain.preset import Preset, get_preset, list_presets
from ...users import (
    get_settings_for, set_auto_trade, set_paused, update_settings, upsert_user,
)
from ...wallet.ledger import daily_pnl, get_balance
from ..keyboards.presets import (
    preset_confirm, preset_picker, preset_status, preset_stop_confirm,
    preset_switch_confirm,
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

def _preset_picker_text() -> str:
    lines = ["*🤖 Auto-Trade Preset*\n",
             "Pick a preset to bundle strategy + risk + sizing in one tap."
             " ⭐ marks the recommended starting preset.\n"]
    for p in list_presets():
        lines.append(
            f"{p.emoji} *{p.name}* ({p.badge.value})\n"
            f"   _{p.description}_"
        )
    return "\n\n".join(lines)


def _preset_confirm_text(p: Preset) -> str:
    strategies = ", ".join(s.replace("_", " ").title() for s in p.strategies)
    return (
        f"*{p.emoji} {p.name}* — {p.badge.value}\n\n"
        f"_{p.description}_\n\n"
        "*Configuration*\n"
        f"├ Strategies     : `{strategies}`\n"
        f"├ Capital        : `{p.capital_pct * 100:.0f}%` of balance\n"
        f"├ Take-profit    : `+{p.tp_pct * 100:.0f}%`\n"
        f"├ Stop-loss      : `-{p.sl_pct * 100:.0f}%`\n"
        f"└ Max position   : `{p.max_position_pct * 100:.0f}%` per trade\n\n"
        "Activate to apply these settings and turn auto-trade ON "
        "(paper mode). Customize is coming in Phase 5D."
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
        state = "🛑 STOPPED"
    elif paused:
        state = "⏸ PAUSED"
    else:
        state = "✅ RUNNING"
    return (
        f"*{p.emoji} {p.name}* — {p.badge.value}\n"
        f"State: *{state}*\n\n"
        "*Live stats*\n"
        f"├ Balance        : `${float(bal):.2f}`\n"
        f"├ Today's P&L    : `${float(pnl):+.2f}`\n"
        f"└ Open positions : `{int(open_count)}`\n\n"
        "*Active config*\n"
        f"├ Capital        : `{p.capital_pct * 100:.0f}%`\n"
        f"├ TP / SL        : `+{p.tp_pct * 100:.0f}% / -{p.sl_pct * 100:.0f}%`\n"
        f"└ Max position   : `{p.max_position_pct * 100:.0f}%`"
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

async def show_preset_picker(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the 5-preset picker card."""
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    # Clear any half-finished setup prompt so the picker isn't fighting an
    # awaiting capital_pct / tpsl input from the legacy flow.
    if ctx.user_data:
        ctx.user_data.pop("awaiting", None)
    await _reply(
        update, _preset_picker_text(),
        parse_mode=ParseMode.MARKDOWN, reply_markup=preset_picker(),
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
        "✏️ Customize wizard ships in Phase 5D. For now the preset values "
        "are activated as-is.",
    )


async def _on_edit(update: Update) -> None:
    await _reply(
        update,
        "✏️ Inline edit ships in Phase 5D. To change settings now, *Switch* "
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
