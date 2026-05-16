"""Phase 5 UX Rebuild — Auto-Trade handler (Screen 03 + 04).

Screen 03 — Preset Picker (no active preset or switch requested)
Screen 04 — Preset Confirmation (preset selected)
Screen 04b — Active Preset Status (preset already running)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import set_auto_trade, set_paused, upsert_user, update_settings
from ...wallet.ledger import daily_pnl
from ..keyboards import preset_active_kb, preset_confirm_kb, preset_picker_kb
from ..messages import (
    PRESET_PICKER_TEXT,
    preset_activated_success_text,
    preset_active_text,
    preset_confirm_text,
)
from ..presets import PRESET_CONFIG, get_preset

logger = logging.getLogger(__name__)


async def _get_active_preset(user_id) -> tuple[str | None, dict]:
    """Return (preset_key, user_settings_row)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        sett = await conn.fetchrow(
            "SELECT active_preset, capital_alloc_pct, tp_pct, sl_pct "
            "FROM user_settings WHERE user_id = $1",
            user_id,
        )
    if sett is None:
        return None, {}
    return sett["active_preset"], dict(sett)


async def _safe_edit(q, text: str, **kwargs) -> None:
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            await q.message.reply_text(text, **kwargs)


# ── Screen 03 — Preset Picker ──────────────────────────────────────────────────

async def show_autotrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point — routes to picker or active status depending on user state."""
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    preset_key, sett = await _get_active_preset(user["id"])

    if user.get("auto_trade_on") and preset_key:
        await _show_active_status(update, ctx, user, preset_key, sett)
    else:
        await _show_preset_picker(update, ctx)


async def _show_preset_picker(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(
            q, PRESET_PICKER_TEXT,
            parse_mode=ParseMode.HTML, reply_markup=preset_picker_kb(),
        )
    elif update.message is not None:
        await update.message.reply_text(
            PRESET_PICKER_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=preset_picker_kb(),
        )


async def show_preset_picker(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_preset_picker(update, ctx)


# ── Screen 04 — Preset Confirmation ───────────────────────────────────────────

async def _show_preset_confirm(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    preset_key: str,
) -> None:
    cfg = get_preset(preset_key)
    if cfg is None:
        return
    text = preset_confirm_text(
        preset_emoji=cfg["emoji"],
        preset_name=cfg["name"],
        strategy_label=cfg["strategy_label"],
        risk_emoji=cfg["risk_emoji"],
        risk_label=cfg["risk_label"],
        capital_pct=cfg["capital_pct"],
        tp_pct=cfg["tp_pct"],
        sl_pct=cfg["sl_pct"],
        max_pos_pct=cfg["max_pos_pct"],
    )
    ctx.user_data["p5_pending_preset"] = preset_key
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=preset_confirm_kb())
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=preset_confirm_kb(),
        )


async def _show_active_status(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    user: dict,
    preset_key: str,
    sett: dict,
) -> None:
    cfg = get_preset(preset_key)
    if cfg is None:
        await _show_preset_picker(update, ctx)
        return

    pnl_today = await daily_pnl(user["id"])
    pool = get_pool()
    async with pool.acquire() as conn:
        trades_today = await conn.fetchval(
            """SELECT COUNT(*) FROM positions
               WHERE user_id=$1 AND opened_at >= CURRENT_DATE""",
            user["id"],
        ) or 0
        activated_at = await conn.fetchval(
            "SELECT preset_activated_at FROM user_settings WHERE user_id=$1",
            user["id"],
        )

    activated_str = (
        activated_at.strftime("%Y-%m-%d %H:%M")
        if activated_at else "—"
    )
    capital_pct = int(float(sett.get("capital_alloc_pct", cfg["capital_pct"] / 100)) * 100)
    tp_pct = int(float(sett.get("tp_pct") or cfg["tp_pct"] / 100) * 100)
    sl_pct = int(float(sett.get("sl_pct") or cfg["sl_pct"] / 100) * 100)

    text = preset_active_text(
        preset_emoji=cfg["emoji"],
        preset_name=cfg["name"],
        activated_date=activated_str,
        trades_today=trades_today,
        pnl_today=pnl_today,
        strategy_label=cfg["strategy_label"],
        risk_emoji=cfg["risk_emoji"],
        risk_label=cfg["risk_label"],
        capital_pct=capital_pct,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
    )
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=preset_active_kb())
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=preset_active_kb(),
        )


# ── Callback handler ───────────────────────────────────────────────────────────

async def autotrade_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes all p5:preset:*, p5:confirm:*, p5:active:* callbacks."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    data = q.data or ""

    if data.startswith("p5:preset:"):
        preset_key = data.split(":", 2)[-1]
        await _show_preset_confirm(update, ctx, preset_key)
        return

    if data.startswith("p5:confirm:"):
        action = data.split(":", 2)[-1]
        await _handle_confirm_action(update, ctx, action)
        return

    if data.startswith("p5:active:"):
        action = data.split(":", 2)[-1]
        await _handle_active_action(update, ctx, action)
        return


async def _handle_confirm_action(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str,
) -> None:
    q = update.callback_query
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    if action == "activate":
        preset_key = ctx.user_data.get("p5_pending_preset")
        if not preset_key:
            await _show_preset_picker(update, ctx)
            return
        await _activate_preset(update, ctx, user, preset_key)

    elif action == "customize":
        preset_key = ctx.user_data.get("p5_pending_preset")
        if preset_key:
            ctx.user_data["p5_customize_preset"] = preset_key
        from .customize import start_customize_wizard
        await start_customize_wizard(update, ctx)

    elif action == "back":
        await _show_preset_picker(update, ctx)


async def _activate_preset(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    user: dict,
    preset_key: str,
) -> None:
    cfg = get_preset(preset_key)
    if cfg is None:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE user_settings SET
                active_preset     = $2,
                capital_alloc_pct = $3,
                tp_pct            = $4,
                sl_pct            = $5,
                strategy_types    = $6,
                max_position_pct  = $7,
                preset_activated_at = NOW()
               WHERE user_id = $1""",
            user["id"],
            preset_key,
            cfg["capital_pct"] / 100.0,
            cfg["tp_pct"] / 100.0,
            cfg["sl_pct"] / 100.0,
            cfg["strategies"],
            cfg["max_pos_pct"] / 100.0,
        )
    await set_auto_trade(user["id"], True)
    ctx.user_data.pop("p5_pending_preset", None)

    text = preset_activated_success_text(cfg["emoji"], cfg["name"])
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML)
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    from .dashboard import show_dashboard_for_cb
    await show_dashboard_for_cb(update, ctx)


async def _handle_active_action(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str,
) -> None:
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    if action == "edit":
        preset_key, sett = await _get_active_preset(user["id"])
        if preset_key:
            ctx.user_data["p5_customize_preset"] = preset_key
        from .customize import start_customize_wizard
        await start_customize_wizard(update, ctx)

    elif action == "switch":
        await _show_preset_picker(update, ctx)

    elif action == "pause":
        await set_paused(user["id"], True)
        from .dashboard import show_dashboard_for_cb
        await show_dashboard_for_cb(update, ctx)

    elif action == "stop":
        await set_auto_trade(user["id"], False)
        from .dashboard import show_dashboard_for_cb
        await show_dashboard_for_cb(update, ctx)
