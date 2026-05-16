"""Phase 5 UX Rebuild — /start handler + onboarding flow (Screen 01).

New users:  Welcome → Wallet init → Preset Picker → Deposit prompt
Returning users:  /start → Dashboard (Screen 02)

Returning = users.onboarding_complete is True in the DB.
"""
from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from ...database import get_pool
from ...users import set_onboarding_complete, upsert_user
from ...wallet.ledger import get_balance
from ...wallet.vault import get_wallet
from ..keyboards import (
    deposit_prompt_kb,
    wallet_ready_kb,
    welcome_back_kb,
    welcome_kb,
)
from ..messages import (
    LEARN_MORE_TEXT,
    WELCOME_TEXT,
    deposit_prompt_text,
    wallet_ready_text,
)

logger = logging.getLogger(__name__)

# ConversationHandler states
_WELCOME = 0
_WALLET_READY = 1
_DEPOSIT = 2

_PAPER_SEED = 1000.0


async def _get_address(user_id) -> str:
    w = await get_wallet(user_id)
    return w["deposit_address"] if w else "(not set)"


async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    if user.get("onboarding_complete"):
        from .dashboard import show_dashboard
        await show_dashboard(update, ctx, user=user)
        return ConversationHandler.END

    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=welcome_kb(),
    )
    return _WELCOME


async def get_started_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return ConversationHandler.END
    await q.answer()
    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    # Seed $1,000 paper balance on first visit if balance is still 0
    try:
        balance = await get_balance(user["id"])
        if float(balance) == 0:
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO wallets (user_id, balance_usdc) VALUES ($1, 1000) "
                    "ON CONFLICT (user_id) DO UPDATE SET balance_usdc = "
                    "  CASE WHEN wallets.balance_usdc = 0 "
                    "       THEN 1000 ELSE wallets.balance_usdc END",
                    user["id"],
                )
                await conn.execute(
                    "INSERT INTO ledger (user_id, type, amount_usdc, note) "
                    "VALUES ($1, 'deposit', 1000, 'Paper wallet — initial $1,000 credit') "
                    "ON CONFLICT DO NOTHING",
                    user["id"],
                )
    except Exception as exc:
        logger.warning("paper seed failed user=%s err=%s", user["id"], exc)

    address = await _get_address(user["id"])
    await q.edit_message_text(
        wallet_ready_text(address),
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_ready_kb(),
    )
    ctx.user_data["onboard_address"] = address
    return _WALLET_READY


async def learn_more_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return _WELCOME
    await q.answer()
    await q.edit_message_text(
        LEARN_MORE_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=welcome_back_kb(),
    )
    return _WELCOME


async def back_to_welcome_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return _WELCOME
    await q.answer()
    await q.edit_message_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=welcome_kb(),
    )
    return _WELCOME


async def copy_address_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Show address as alert. Returns the current onboarding state so the user
    stays in whichever step (wallet_ready or deposit) they were on."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()
    address = ctx.user_data.get("onboard_address", "")
    if address and address != "(not set)":
        await q.answer(f"Address: {address}", show_alert=True)
    else:
        await q.answer("Address not available yet.", show_alert=True)
    # Stay in whichever state brought us here; use flag set by wallet_next_cb / preset_selected_in_onboard_cb
    return _DEPOSIT if ctx.user_data.get("_onboard_at_deposit") else _WALLET_READY


async def wallet_next_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Move from wallet confirmation → preset picker (Screen 03)."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return ConversationHandler.END
    await q.answer()
    from ..messages import PRESET_PICKER_TEXT
    from ..keyboards import preset_picker_kb
    await q.edit_message_text(
        PRESET_PICKER_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=preset_picker_kb(),
    )
    ctx.user_data["onboard_in_preset_step"] = True
    ctx.user_data["_onboard_at_deposit"] = False  # still on preset picker, not deposit yet
    return _DEPOSIT


async def preset_selected_in_onboard_cb(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Preset chosen during onboarding — show deposit prompt after saving."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return ConversationHandler.END
    await q.answer()
    preset_key = (q.data or "").split(":", 2)[-1]
    ctx.user_data["onboard_preset_key"] = preset_key

    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    address = ctx.user_data.get("onboard_address") or await _get_address(user["id"])

    ctx.user_data["_onboard_at_deposit"] = True  # now on deposit prompt; copy_address stays in _DEPOSIT
    await q.edit_message_text(
        deposit_prompt_text(address),
        parse_mode=ParseMode.HTML,
        reply_markup=deposit_prompt_kb(),
    )
    return _DEPOSIT


async def skip_deposit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip deposit → mark onboarding complete → Dashboard."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return ConversationHandler.END
    await q.answer()
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    await set_onboarding_complete(user["id"], True)
    ctx.user_data.pop("onboard_in_preset_step", None)
    ctx.user_data.pop("onboard_address", None)
    ctx.user_data.pop("onboard_preset_key", None)

    from .dashboard import show_dashboard_for_cb
    await show_dashboard_for_cb(update, ctx)
    return ConversationHandler.END


def build_start_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            _WELCOME: [
                CallbackQueryHandler(get_started_cb,    pattern=r"^start:get_started$"),
                CallbackQueryHandler(learn_more_cb,     pattern=r"^start:learn_more$"),
                CallbackQueryHandler(back_to_welcome_cb, pattern=r"^start:welcome$"),
            ],
            _WALLET_READY: [
                CallbackQueryHandler(copy_address_cb,   pattern=r"^start:copy_address$"),
                CallbackQueryHandler(wallet_next_cb,    pattern=r"^start:wallet_next$"),
            ],
            _DEPOSIT: [
                CallbackQueryHandler(preset_selected_in_onboard_cb,
                                     pattern=r"^p5:preset:"),
                CallbackQueryHandler(copy_address_cb,   pattern=r"^start:copy_address$"),
                CallbackQueryHandler(skip_deposit_cb,   pattern=r"^start:skip_deposit$"),
            ],
        },
        fallbacks=[CommandHandler("start", start_command)],
        allow_reentry=True,
        name="p5_start",
        persistent=False,
    )


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    from ...config import get_settings
    settings = get_settings()
    tg_id = update.effective_user.id
    is_op = bool(settings.OPERATOR_CHAT_ID and tg_id == settings.OPERATOR_CHAT_ID)

    user_commands = (
        "<b>📋 Commands</b>\n\n"
        "/start — Welcome &amp; onboarding\n"
        "/dashboard — Main dashboard\n"
        "/trades — View your trades\n"
        "/positions — Open positions\n"
        "/settings — Configure preferences\n"
        "/preset — Strategy presets\n"
        "/wallet — Wallet &amp; deposits\n"
        "/emergency — Emergency controls\n"
        "/insights — P&amp;L insights\n"
        "/chart — Portfolio chart\n"
        "/summary_on — Enable daily summary\n"
        "/summary_off — Disable daily summary\n"
        "/help — This help\n"
    )

    admin_commands = (
        "\n<b>🔧 Admin</b>\n"
        "/admin — Admin panel\n"
        "/ops_dashboard — Ops overview\n"
        "/health — System health\n"
        "/jobs — Scheduler jobs\n"
        "/killswitch — Emergency kill\n"
        "/auditlog — Audit trail\n"
    ) if is_op else ""

    await update.message.reply_text(
        user_commands + admin_commands,
        parse_mode=ParseMode.HTML,
    )
