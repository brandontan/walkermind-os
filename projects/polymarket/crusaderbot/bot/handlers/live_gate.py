"""Track F — 3-step Live Opt-In Gate Telegram handler.

Flow:
  /enable_live
      └─ guard check (4 global flags) → block if any NOT SET
      └─ Step 1: warning screen → arm awaiting=live_gate_step1
  User types "CONFIRM" (exact, case-sensitive)
      └─ Step 2 consumed → show inline keyboard → arm awaiting=live_gate_step2
         timestamp stored so 10-second window can be enforced
  User taps [YES, ENABLE LIVE] or [CANCEL] (callback live_gate:yes / live_gate:cancel)
      └─ Step 3: if YES within 10s → write mode_change_events + update trading_mode
         else → cancel / timeout message

No activation guard is set here. Only user_settings.trading_mode is written.
"""
from __future__ import annotations

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...domain.activation.live_opt_in_gate import (
    ModeChangeReason,
    check_activation_guards,
    write_mode_change_event,
)
from ...users import get_settings_for, update_settings, upsert_user

logger = logging.getLogger(__name__)

AWAITING_KEY = "awaiting"
AWAITING_STEP1 = "live_gate_step1"
AWAITING_STEP2 = "live_gate_step2"
GATE_TS_KEY = "live_gate_ts"

CONFIRMATION_TIMEOUT_SECONDS: float = 10.0


# ── helpers ───────────────────────────────────────────────────────────────────


def _step3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ YES, ENABLE LIVE", callback_data="live_gate:yes"),
        InlineKeyboardButton("❌ CANCEL", callback_data="live_gate:cancel"),
    ]])


async def _reply_text(update: Update, text: str) -> None:
    if update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    elif (
        update.callback_query is not None
        and update.callback_query.message is not None
    ):
        await update.callback_query.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN,
        )


# ── /enable_live command ──────────────────────────────────────────────────────


async def enable_live_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Entry point — guard check then Step 1 warning."""
    if update.effective_user is None or update.message is None:
        return

    guard_result = check_activation_guards()
    if not guard_result.all_set:
        await update.message.reply_text(
            "🔒 Live trading not available\\. Prerequisites not met\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if ctx.user_data is not None:
        ctx.user_data[AWAITING_KEY] = AWAITING_STEP1
        ctx.user_data.pop(GATE_TS_KEY, None)

    await update.message.reply_text(
        "⚠️ *You are about to enable LIVE trading.*\n\n"
        "Real money will be used\\. Losses are possible\\.\n\n"
        "Type *CONFIRM* to proceed\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── text_input (Step 2 consumer) ──────────────────────────────────────────────


async def text_input(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Consume the CONFIRM reply from Step 1.

    Returns True when this handler consumed the message (preventing fall-through).
    Returns False when the message was not part of this flow.
    """
    if update.message is None or update.effective_user is None:
        return False

    awaiting = ctx.user_data.get(AWAITING_KEY) if ctx.user_data else None
    if awaiting != AWAITING_STEP1:
        return False

    text = (update.message.text or "").strip()
    if ctx.user_data is not None:
        ctx.user_data.pop(AWAITING_KEY, None)

    if text != "CONFIRM":
        await update.message.reply_text(
            "Cancelled\\. Live mode activation aborted\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return True

    # Step 2 passed — advance to Step 3: show the final confirmation button
    if ctx.user_data is not None:
        ctx.user_data[AWAITING_KEY] = AWAITING_STEP2
        ctx.user_data[GATE_TS_KEY] = time.monotonic()

    await update.message.reply_text(
        "Are you absolutely sure\\? This cannot be undone automatically\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_step3_keyboard(),
    )
    return True


# ── callback handler (Step 3) ─────────────────────────────────────────────────


async def live_gate_callback(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle live_gate:yes and live_gate:cancel callbacks."""
    if update.callback_query is None or update.effective_user is None:
        return

    query = update.callback_query
    await query.answer()

    awaiting = ctx.user_data.get(AWAITING_KEY) if ctx.user_data else None
    if awaiting != AWAITING_STEP2:
        if query.message:
            await query.message.reply_text(
                "No active confirmation\\. Use /enable\\_live to start\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        return

    if ctx.user_data is not None:
        ctx.user_data.pop(AWAITING_KEY, None)

    action = (query.data or "").removeprefix("live_gate:")

    if action == "cancel":
        if query.message:
            await query.message.reply_text(
                "Cancelled\\. Live mode not enabled\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        return

    if action == "yes":
        gate_ts: float = (
            ctx.user_data.pop(GATE_TS_KEY, 0.0) if ctx.user_data else 0.0
        )
        elapsed = time.monotonic() - gate_ts
        if elapsed > CONFIRMATION_TIMEOUT_SECONDS:
            if query.message:
                await query.message.reply_text(
                    "⏱ Confirmation window expired \\(10 seconds\\)\\. "
                    "Use /enable\\_live to restart\\.",
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            return

        user = await upsert_user(
            update.effective_user.id, update.effective_user.username,
        )
        settings_row = await get_settings_for(user["id"])
        from_mode = settings_row.get("trading_mode") or "paper"

        await update_settings(user["id"], trading_mode="live")
        await write_mode_change_event(
            user_id=user["id"],
            from_mode=from_mode,
            to_mode="live",
            reason=ModeChangeReason.USER_CONFIRMED,
        )

        if query.message:
            await query.message.reply_text(
                "🟢 *LIVE trading mode enabled\\.* "
                "All risk gates remain active on every signal\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        return

    # Unknown action — silently ignore
    logger.warning("live_gate_callback unknown action=%s", action)
