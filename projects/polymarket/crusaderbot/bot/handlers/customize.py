"""Phase 5 UX Rebuild — Customize Wizard (ConversationHandler, 5 steps).

Step 1/5 — Capital Allocation
Step 2/5 — Take Profit
Step 3/5 — Stop Loss
Step 4/5 — Copy Targets (copy_trade strategy only)
Step 5/5 — Review
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ...database import get_pool
from ...users import upsert_user
from ..keyboards import (
    customize_capital_kb,
    customize_review_kb,
    customize_sl_kb,
    customize_targets_kb,
    customize_tp_kb,
)
from ..presets import get_preset

logger = logging.getLogger(__name__)

# ConversationHandler states
_CAP = 0
_TP = 1
_SL = 2
_TARGETS = 3
_REVIEW = 4

_AWAITING_CUSTOM = "p5_customize_custom"


async def _safe_edit(q, text: str, **kwargs) -> None:
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            await q.message.reply_text(text, **kwargs)


async def start_customize_wizard(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Entry point — called from autotrade.py on [Customize] or [Edit Config]."""
    preset_key = ctx.user_data.get("p5_customize_preset")
    cfg = get_preset(preset_key) if preset_key else None

    # Seed defaults from preset or current settings
    if cfg:
        ctx.user_data.setdefault("p5_wiz_cap", cfg["capital_pct"])
        ctx.user_data.setdefault("p5_wiz_tp", cfg["tp_pct"])
        ctx.user_data.setdefault("p5_wiz_sl", cfg["sl_pct"])
        ctx.user_data.setdefault("p5_wiz_has_copy", cfg["has_copy_trade"])
    else:
        ctx.user_data.setdefault("p5_wiz_cap", 50)
        ctx.user_data.setdefault("p5_wiz_tp", 15)
        ctx.user_data.setdefault("p5_wiz_sl", 10)
        ctx.user_data.setdefault("p5_wiz_has_copy", False)

    await _send_step1(update, ctx)
    return _CAP


async def _send_step1(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cap = ctx.user_data.get("p5_wiz_cap", 50)
    text = (
        "<b>⚙️ Customize — Step 1/5</b>\n\n"
        "<b>Capital Allocation</b>\n"
        "How much of your balance to deploy?\n\n"
        f"<i>Current: {cap}%</i>"
    )
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=customize_capital_kb())
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=customize_capital_kb(),
        )


async def _send_step2(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tp = ctx.user_data.get("p5_wiz_tp", 15)
    text = (
        "<b>⚙️ Customize — Step 2/5</b>\n\n"
        "<b>Take Profit</b>\n"
        "Auto-close winning positions at:\n\n"
        f"<i>Current: +{tp}%</i>"
    )
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=customize_tp_kb())
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=customize_tp_kb(),
        )


async def _send_step3(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    sl = ctx.user_data.get("p5_wiz_sl", 10)
    text = (
        "<b>⚙️ Customize — Step 3/5</b>\n\n"
        "<b>Stop Loss</b>\n"
        "Auto-close losing positions at:\n\n"
        f"<i>Current: -{sl}%</i>"
    )
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=customize_sl_kb())
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=customize_sl_kb(),
        )


async def _send_step4(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>⚙️ Customize — Step 4/5</b>\n\n"
        "<b>Copy Targets</b>\n"
        "Enter wallet addresses to follow:"
    )
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=customize_targets_kb())
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=customize_targets_kb(),
        )


async def _send_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cap = ctx.user_data.get("p5_wiz_cap", 50)
    tp = ctx.user_data.get("p5_wiz_tp", 15)
    sl = ctx.user_data.get("p5_wiz_sl", 10)
    preset_key = ctx.user_data.get("p5_customize_preset", "")
    cfg = get_preset(preset_key)
    preset_label = f"{cfg['emoji']} {cfg['name']}" if cfg else preset_key or "Custom"

    text = (
        "<b>⚙️ Customize — Step 5/5</b>\n\n"
        "<b>Review</b>\n\n"
        "<pre>"
        f"Preset:   {preset_label}\n"
        f"Capital:  {cap}%\n"
        f"TP:       +{tp}%\n"
        f"SL:       -{sl}%\n"
        f"Mode:     📝 Paper"
        "</pre>"
    )
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=customize_review_kb())
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=customize_review_kb(),
        )


# ── Step callbacks ─────────────────────────────────────────────────────────────

async def cap_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return _CAP
    await q.answer()
    val = (q.data or "").split(":")[-1]
    if val == "custom":
        ctx.user_data[_AWAITING_CUSTOM] = "cap"
        await _safe_edit(
            q,
            "<b>⚙️ Customize — Step 1/5</b>\n\n"
            "Enter custom capital percentage (1–100):",
            parse_mode=ParseMode.HTML,
        )
        return _CAP
    try:
        ctx.user_data["p5_wiz_cap"] = int(val)
    except ValueError:
        pass
    await _send_step2(update, ctx)
    return _TP


async def tp_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return _TP
    await q.answer()
    val = (q.data or "").split(":")[-1]
    if val == "custom":
        ctx.user_data[_AWAITING_CUSTOM] = "tp"
        await _safe_edit(
            q,
            "<b>⚙️ Customize — Step 2/5</b>\n\n"
            "Enter custom take profit % (e.g. 25):",
            parse_mode=ParseMode.HTML,
        )
        return _TP
    try:
        ctx.user_data["p5_wiz_tp"] = int(val)
    except ValueError:
        pass
    await _send_step3(update, ctx)
    return _SL


async def sl_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return _SL
    await q.answer()
    val = (q.data or "").split(":")[-1]
    if val == "custom":
        ctx.user_data[_AWAITING_CUSTOM] = "sl"
        await _safe_edit(
            q,
            "<b>⚙️ Customize — Step 3/5</b>\n\n"
            "Enter custom stop loss % (e.g. 12):",
            parse_mode=ParseMode.HTML,
        )
        return _SL
    try:
        ctx.user_data["p5_wiz_sl"] = int(val)
    except ValueError:
        pass
    has_copy = ctx.user_data.get("p5_wiz_has_copy", False)
    if has_copy:
        await _send_step4(update, ctx)
        return _TARGETS
    await _send_review(update, ctx)
    return _REVIEW


async def targets_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return _TARGETS
    await q.answer()
    # skip or browse → move to review
    await _send_review(update, ctx)
    return _REVIEW


async def review_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return _REVIEW
    await q.answer()
    data = q.data or ""

    if data == "p5:customize:save":
        await _save_customize(update, ctx)
        return ConversationHandler.END

    if data == "p5:customize:back":
        has_copy = ctx.user_data.get("p5_wiz_has_copy", False)
        if has_copy:
            await _send_step4(update, ctx)
            return _TARGETS
        await _send_step3(update, ctx)
        return _SL

    return _REVIEW


async def _save_customize(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    cap = ctx.user_data.get("p5_wiz_cap", 50)
    tp = ctx.user_data.get("p5_wiz_tp", 15)
    sl = ctx.user_data.get("p5_wiz_sl", 10)
    preset_key = ctx.user_data.get("p5_customize_preset")

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE user_settings SET
                capital_alloc_pct = $2,
                tp_pct            = $3,
                sl_pct            = $4
               WHERE user_id = $1""",
            user["id"],
            cap / 100.0,
            tp / 100.0,
            sl / 100.0,
        )

    for key in ("p5_wiz_cap", "p5_wiz_tp", "p5_wiz_sl", "p5_wiz_has_copy",
                "p5_customize_preset", _AWAITING_CUSTOM):
        ctx.user_data.pop(key, None)

    from .dashboard import show_dashboard_for_cb
    await show_dashboard_for_cb(update, ctx)


async def _text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle free-text input for custom numeric values."""
    if update.message is None:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    field = ctx.user_data.get(_AWAITING_CUSTOM)
    if not field:
        return ConversationHandler.END

    try:
        val = int(float(text))
        if val <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Please enter a positive number.", parse_mode=ParseMode.HTML,
        )
        return _CAP if field == "cap" else (_TP if field == "tp" else _SL)

    ctx.user_data[f"p5_wiz_{field}"] = val
    ctx.user_data.pop(_AWAITING_CUSTOM, None)

    if field == "cap":
        await _send_step2(update, ctx)
        return _TP
    if field == "tp":
        await _send_step3(update, ctx)
        return _SL
    # sl
    has_copy = ctx.user_data.get("p5_wiz_has_copy", False)
    if has_copy:
        await _send_step4(update, ctx)
        return _TARGETS
    await _send_review(update, ctx)
    return _REVIEW


def build_customize_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_customize_wizard, pattern=r"^p5:confirm:customize$"),
            CallbackQueryHandler(start_customize_wizard, pattern=r"^p5:active:edit$"),
        ],
        states={
            _CAP: [
                CallbackQueryHandler(cap_cb, pattern=r"^p5:customize:cap:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _text_input),
            ],
            _TP: [
                CallbackQueryHandler(tp_cb, pattern=r"^p5:customize:tp:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _text_input),
            ],
            _SL: [
                CallbackQueryHandler(sl_cb, pattern=r"^p5:customize:sl:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _text_input),
            ],
            _TARGETS: [
                CallbackQueryHandler(targets_cb, pattern=r"^p5:customize:targets:"),
            ],
            _REVIEW: [
                CallbackQueryHandler(review_cb, pattern=r"^p5:customize:(save|back)$"),
            ],
        },
        fallbacks=[],
        allow_reentry=True,
        name="p5_customize",
        persistent=False,
    )
