"""R12 Telegram handlers for live activation + daily summary toggle.

Three commands and one shared text confirmation:

    /live_checklist  — run all 8 activation gates, surface pass/fix list
    /summary_on      — opt back into the daily P&L summary
    /summary_off     — opt out of the daily P&L summary

When a user toggles auto-trade ON while their ``trading_mode`` is
``live``, ``autotrade_toggle_pending_confirm`` arms a short-lived
``ctx.user_data['awaiting']='confirm_live_autotrade'`` flag. The text
router routes the next plain message to :func:`text_input` here, which
only flips ``users.auto_trade_on=true`` after the user types CONFIRM
(case-insensitive). Anything else cancels the arming.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...domain.activation import live_checklist
from ...jobs import daily_pnl_summary
from ...users import get_settings_for, set_auto_trade, update_settings, upsert_user

logger = logging.getLogger(__name__)


AWAITING_KEY = "awaiting"
AWAITING_LIVE_CONFIRM = "confirm_live_autotrade"
AWAITING_TRADING_MODE_LIVE_CONFIRM = "confirm_trading_mode_live"


# ---------------- /live_checklist -------------------------------------------


async def live_checklist_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    result = await live_checklist.evaluate(user["id"])
    await update.message.reply_text(
        live_checklist.render_telegram(result),
        parse_mode=ParseMode.HTML,
    )


# ---------------- /summary_on /summary_off ----------------------------------


async def summary_on_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    await daily_pnl_summary.set_summary_enabled(user["id"], True)
    await update.message.reply_text(
        "✅ Daily P&L summary <b>enabled</b>. You'll receive a one-message "
        "summary at 23:00 Asia/Jakarta each day.",
        parse_mode=ParseMode.HTML,
    )


async def summary_off_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    await daily_pnl_summary.set_summary_enabled(user["id"], False)
    await update.message.reply_text(
        "🔕 Daily P&L summary <b>disabled</b>. Use /summary_on to turn it "
        "back on.",
        parse_mode=ParseMode.HTML,
    )


# ---------------- LIVE auto-trade confirmation ------------------------------


async def _reply(update: Update, text: str) -> None:
    """Send an HTML reply onto whichever surface the update came in on."""
    if update.callback_query is not None and update.callback_query.message:
        await update.callback_query.message.reply_text(
            text, parse_mode=ParseMode.HTML,
        )
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def autotrade_toggle_pending_confirm(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Arm a CONFIRM flow if the toggle would enable LIVE auto-trade.

    Returns True when this handler has fully consumed the toggle (either
    because CONFIRM was armed or because the checklist refused the flip
    and we surfaced the fix list). The caller MUST NOT flip
    ``auto_trade_on`` itself in that case. Returns False only when this
    is a paper-mode toggle or an OFF toggle, in which case the caller
    should run its normal flip path.
    """
    if update.effective_user is None:
        return False
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    settings_row = await get_settings_for(user["id"])
    # Only require CONFIRM when ALL of:
    #   * the user is currently OFF (this toggle would turn ON)
    #   * their configured trading_mode is 'live' (so the flip would
    #     submit real CLOB orders)
    if user["auto_trade_on"]:
        return False
    if (settings_row.get("trading_mode") or "paper") != "live":
        return False
    # Re-run the full activation checklist BEFORE arming CONFIRM. The
    # /setup live-mode picker only blocks on Tier + global flags, and
    # the risk gate's live selection only checks globals + tier +
    # trading_mode — neither enforces 2FA or the active-subaccount /
    # configured-strategy gates. Without this re-evaluation a user
    # whose checklist is failing could still type CONFIRM and route a
    # real CLOB order. Surface the fix list and refuse the flip when
    # any gate fails so the checklist is a hard pre-activation gate.
    result = await live_checklist.evaluate(user["id"])
    if not result.ready_for_live:
        await _reply(update, live_checklist.render_telegram(result))
        return True
    if ctx.user_data is not None:
        ctx.user_data[AWAITING_KEY] = AWAITING_LIVE_CONFIRM
    await _reply(
        update,
        "⚠️ <b>You are enabling LIVE trading with real capital.</b>\n"
        "All activation gates have passed.\n\n"
        "Type <b>CONFIRM</b> (in capitals) to proceed, or anything else to "
        "cancel.",
    )
    return True


async def trading_mode_live_pending_confirm(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Arm CONFIRM when ``/setup`` would switch ``trading_mode`` to live.

    Returns True when this handler has fully consumed the picker
    interaction (either CONFIRM was armed or the checklist refused with
    a fix list). The caller (``setup.set_mode``) MUST NOT call
    ``update_settings(trading_mode='live')`` in that case — the actual
    write happens in :func:`text_input` after the user types CONFIRM.
    Returns False to let the caller proceed (paper switch, or live
    switch that for some reason should not gate — currently never).
    """
    if update.effective_user is None:
        return False
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    result = await live_checklist.evaluate(user["id"])
    if not result.ready_for_live:
        await _reply(update, live_checklist.render_telegram(result))
        return True
    if ctx.user_data is not None:
        ctx.user_data[AWAITING_KEY] = AWAITING_TRADING_MODE_LIVE_CONFIRM
    await _reply(
        update,
        "⚠️ <b>You are switching trading mode to LIVE — real capital.</b>\n"
        "All activation gates have passed.\n\n"
        "If your auto-trade is already ON, the next signal will route "
        "as a real Polymarket order.\n\n"
        "Type <b>CONFIRM</b> (in capitals) to proceed, or anything else to "
        "cancel.",
    )
    return True


async def text_input(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Consume the CONFIRM reply if one is awaited.

    Wired into :func:`bot.dispatcher._text_router`. Returns True when
    the message was a confirmation reply (whether or not the user typed
    CONFIRM exactly) so the dispatcher does not fall through to other
    text routes.
    """
    if update.message is None or update.effective_user is None:
        return False
    awaiting = (
        ctx.user_data.get(AWAITING_KEY) if ctx.user_data else None
    )
    if awaiting not in (
        AWAITING_LIVE_CONFIRM, AWAITING_TRADING_MODE_LIVE_CONFIRM,
    ):
        return False
    text = (update.message.text or "").strip()
    if ctx.user_data is not None:
        ctx.user_data.pop(AWAITING_KEY, None)
    if text != "CONFIRM":
        cancelled_msg = (
            "Cancelled. Auto-trade remains <b>OFF</b>."
            if awaiting == AWAITING_LIVE_CONFIRM
            else "Cancelled. Trading mode unchanged."
        )
        await update.message.reply_text(
            cancelled_msg, parse_mode=ParseMode.HTML,
        )
        return True
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    # Defense-in-depth re-check: the operator could have flipped
    # ENABLE_LIVE_TRADING off, the user's deposit could have been
    # reverted, or 2FA could have been revoked between the prompt and
    # this reply. Re-run the checklist and refuse the flip if any gate
    # has degraded since CONFIRM was armed.
    result = await live_checklist.evaluate(user["id"])
    if not result.ready_for_live:
        await update.message.reply_text(
            live_checklist.render_telegram(result),
            parse_mode=ParseMode.HTML,
        )
        return True
    if awaiting == AWAITING_LIVE_CONFIRM:
        if user.get("locked", False):
            await update.message.reply_text(
                "🔒 Account locked. Contact admin.",
                parse_mode=ParseMode.HTML,
            )
            return True
        await set_auto_trade(user["id"], True)
        await update.message.reply_text(
            "🟢 Auto-trade is now <b>ON</b> in <b>LIVE</b> mode. Existing risk "
            "gates still apply on every signal.",
            parse_mode=ParseMode.HTML,
        )
        return True
    # AWAITING_TRADING_MODE_LIVE_CONFIRM
    await update_settings(user["id"], trading_mode="live")
    await update.message.reply_text(
        "🟢 Trading mode set to <b>LIVE</b>. Existing risk gates still apply "
        "on every signal. Toggle auto-trade to engage.",
        parse_mode=ParseMode.HTML,
    )
    return True
