"""Track F — Live Opt-In Gate Telegram handler (SIMPLE bot-control surface).

This is the Telegram-side twin of the WebTrader live-activation flow
(`webtrader/backend/router.py` /live/{status,enable,disable}). Both surfaces
write the SAME user_settings fields (trading_mode + live_capital_cap_usdc),
run the SAME 8-gate live_checklist, and respect the SAME capital-cap bounds
(shared constants in domain/activation/live_opt_in_gate.py). Telegram is the
"simple" surface: a shorter CONFIRM word instead of the full typed phrase, but
the security effect is identical.

Flow:
  /enable_live
      └─ guard check (4 global flags) → block if any NOT SET
      └─ Step 1: warning + explanation → arm awaiting=live_gate_step1
  User types "CONFIRM" (exact, case-sensitive)
      └─ Step 2: prompt for capital cap → arm awaiting=live_gate_cap
  User types a cap amount (1–10000 USDC)
      └─ validated → stored → Step 3 button shown → arm awaiting=live_gate_step2
         timestamp stored so 10-second window can be enforced
  User taps [YES, ENABLE LIVE] or [CANCEL] (callback live_gate:yes / :cancel)
      └─ if YES within 10s and checklist passes → write trading_mode='live'
         + live_capital_cap_usdc, plus a mode_change_events audit row.

  /disable_live → single-step revert to paper (cap preserved), mirrors the
  WebTrader /live/disable endpoint.

No activation guard is set here. Only user_settings is written.
"""
from __future__ import annotations

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...domain.activation import live_checklist
from ...domain.activation.live_opt_in_gate import (
    LIVE_CAP_MAX_USDC,
    LiveCapError,
    ModeChangeReason,
    check_activation_guards,
    validate_live_capital_cap,
    write_mode_change_event,
)
from ...users import get_settings_for, update_settings, upsert_user

logger = logging.getLogger(__name__)

AWAITING_KEY = "awaiting"
AWAITING_STEP1 = "live_gate_step1"
AWAITING_CAP = "live_gate_cap"
AWAITING_STEP2 = "live_gate_step2"
CAP_KEY = "live_gate_cap_value"
GATE_TS_KEY = "live_gate_ts"

CONFIRMATION_TIMEOUT_SECONDS: float = 10.0


# ── helpers ───────────────────────────────────────────────────────────────────


def _step3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ YES, ENABLE LIVE", callback_data="live_gate:yes"),
        InlineKeyboardButton("❌ CANCEL", callback_data="live_gate:cancel"),
    ]])


def _clear_flow(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if ctx.user_data is None:
        return
    for key in (AWAITING_KEY, CAP_KEY, GATE_TS_KEY):
        ctx.user_data.pop(key, None)


# ── /enable_live command ──────────────────────────────────────────────────────


async def enable_live_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Entry point — guard check then Step 1 warning + plain explanation."""
    if update.effective_user is None or update.message is None:
        return

    guard_result = check_activation_guards()
    if not guard_result.all_set:
        await update.message.reply_text(
            "🔒 *Live trading is not available yet\\.*\n\n"
            "The operator has not finished switching the system to live mode\\. "
            "Your bot stays in *paper mode* \\(practice money, zero risk\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if ctx.user_data is not None:
        _clear_flow(ctx)
        ctx.user_data[AWAITING_KEY] = AWAITING_STEP1

    await update.message.reply_text(
        "⚠️ *Switch to LIVE trading*\n\n"
        "Live mode uses *real USDC* from your wallet\\. Trades can win or lose "
        "real money\\. Paper mode \\(practice\\) is risk\\-free; live mode is not\\.\n\n"
        "All safety gates stay on in live mode \\(position size limit, daily "
        "loss limit, drawdown halt, kill switch\\)\\.\n\n"
        "Type *CONFIRM* to continue, or anything else to cancel\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── /disable_live command (mirror of WebTrader /live/disable) ──────────────────


async def disable_live_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Single-step revert to paper mode. The capital cap is preserved so a
    later /enable_live does not force the user to re-enter it. Open live
    positions are left to resolve; only new trades become paper-mode."""
    if update.effective_user is None or update.message is None:
        return

    _clear_flow(ctx)
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    settings_row = await get_settings_for(user["id"])
    from_mode = settings_row.get("trading_mode") or "paper"

    if from_mode != "live":
        await update.message.reply_text(
            "ℹ️ You are already in *paper mode* \\(practice money\\)\\. "
            "Nothing to disable\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await update_settings(user["id"], trading_mode="paper")
    audit_ok = await write_mode_change_event(
        user_id=user["id"],
        from_mode=from_mode,
        to_mode="paper",
        reason=ModeChangeReason.USER_CONFIRMED,
    )

    msg = (
        "⚪ *Back to paper mode\\.*\n\n"
        "New trades use practice money again \\(no real funds at risk\\)\\. "
        "Your saved capital cap is kept for next time\\.\n\n"
        "To go live again: /enable\\_live"
    )
    if not audit_ok:
        msg += "\n\n_\\(Note: mode changed, but the audit log entry could not be saved\\.\\)_"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


# ── text_input (Step 2 = CONFIRM, Step "cap" = amount) ─────────────────────────


async def text_input(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Consume the CONFIRM reply (Step 1) and the cap amount (cap step).

    Returns True when this handler consumed the message (preventing
    fall-through). Returns False when the message was not part of this flow.
    """
    if update.message is None or update.effective_user is None:
        return False

    awaiting = ctx.user_data.get(AWAITING_KEY) if ctx.user_data else None
    if awaiting not in (AWAITING_STEP1, AWAITING_CAP):
        return False

    text = (update.message.text or "").strip()

    # ── Step 1 consumer: the CONFIRM word ──────────────────────────────────
    if awaiting == AWAITING_STEP1:
        if text != "CONFIRM":
            _clear_flow(ctx)
            await update.message.reply_text(
                "Cancelled\\. Live mode activation aborted\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return True

        # Advance to the capital-cap prompt.
        if ctx.user_data is not None:
            ctx.user_data[AWAITING_KEY] = AWAITING_CAP

        await update.message.reply_text(
            "💰 *Set your live capital cap*\n\n"
            "This is the *maximum USDC of open live positions* the bot may hold "
            "for you at once\\. It is your hard ceiling on live exposure — every "
            "live trade is checked against it before it runs\\.\n\n"
            "Example: a cap of `500` means the bot will never let your combined "
            "open live trades exceed 500 USDC\\.\n\n"
            f"Type an amount between *1* and *{int(LIVE_CAP_MAX_USDC):,}* USDC\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return True

    # ── Cap consumer: validate the amount ──────────────────────────────────
    try:
        cap = validate_live_capital_cap(text)
    except LiveCapError as exc:
        # Stay in the cap step so the user can retry. Plain text (no markdown)
        # so the friendly error never trips MarkdownV2 escaping.
        await update.message.reply_text(f"⚠️ {exc}  —  try again, or send /disable_live to cancel.")
        return True

    if ctx.user_data is not None:
        ctx.user_data[CAP_KEY] = cap
        ctx.user_data[AWAITING_KEY] = AWAITING_STEP2
        ctx.user_data[GATE_TS_KEY] = time.monotonic()

    await update.message.reply_text(
        f"You are about to enable *LIVE* trading with a capital cap of "
        f"`{cap:,.2f} USDC`\\.\n\n"
        "This uses real money\\. Confirm within *10 seconds*\\.",
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

    action = (query.data or "").removeprefix("live_gate:")

    if action == "cancel":
        _clear_flow(ctx)
        if query.message:
            await query.message.reply_text(
                "Cancelled\\. Live mode not enabled\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        return

    if action == "yes":
        gate_ts: float = (
            ctx.user_data.get(GATE_TS_KEY, 0.0) if ctx.user_data else 0.0
        )
        cap = ctx.user_data.get(CAP_KEY, 0.0) if ctx.user_data else 0.0
        _clear_flow(ctx)

        elapsed = time.monotonic() - gate_ts
        if elapsed > CONFIRMATION_TIMEOUT_SECONDS:
            if query.message:
                await query.message.reply_text(
                    "⏱ Confirmation window expired \\(10 seconds\\)\\. "
                    "Use /enable\\_live to restart\\.",
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            return

        # Defensive re-validation of the cap (it came from session state).
        try:
            cap = validate_live_capital_cap(cap)
        except LiveCapError:
            if query.message:
                await query.message.reply_text(
                    "Capital cap was invalid\\. Use /enable\\_live to restart\\.",
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            return

        user = await upsert_user(
            update.effective_user.id, update.effective_user.username,
        )

        # Defense-in-depth: re-run full 8-gate checklist. Guards or user state
        # may have changed between CONFIRM and the button press.
        checklist_result = await live_checklist.evaluate(user["id"])
        if not checklist_result.ready_for_live:
            if query.message:
                await query.message.reply_text(
                    live_checklist.render_telegram(checklist_result),
                    parse_mode=ParseMode.HTML,
                )
            return

        settings_row = await get_settings_for(user["id"])
        from_mode = settings_row.get("trading_mode") or "paper"

        await update_settings(
            user["id"], trading_mode="live", live_capital_cap_usdc=cap,
        )
        audit_ok = await write_mode_change_event(
            user_id=user["id"],
            from_mode=from_mode,
            to_mode="live",
            reason=ModeChangeReason.USER_CONFIRMED,
        )

        if query.message:
            msg = (
                "🟢 *LIVE trading enabled\\.*\n\n"
                f"Capital cap: `{cap:,.2f} USDC` — the most open live exposure "
                "the bot will hold for you\\.\n\n"
                "Every signal still passes all risk gates \\(Kelly 0\\.25, "
                "position ≤10%, daily loss limit, drawdown halt, dedup\\)\\.\n\n"
                "To go back to paper anytime: /disable\\_live"
            )
            if not audit_ok:
                msg += "\n\n_\\(Note: live mode is on, but the audit log entry could not be saved\\.\\)_"
            await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Unknown action — silently ignore
    logger.warning("live_gate_callback unknown action=%s", action)
