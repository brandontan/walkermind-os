"""First-time onboarding flow + returning-user /start routing."""
from __future__ import annotations

import logging
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from ... import audit
from ...config import get_settings
from ...services.referral.referral_service import (
    get_or_create_referral_code,
    parse_ref_param,
    record_referral,
)
from ...users import get_user_by_telegram_id, set_onboarding_complete, upsert_user
from ...wallet.vault import get_wallet
from ..keyboards import main_menu
from ..keyboards.onboarding import get_started_kb, mode_select_kb, paper_complete_kb
from ..tier import Tier, has_tier

logger = logging.getLogger(__name__)

# ConversationHandler state constants
ONBOARD_WELCOME = 0
ONBOARD_MODE = 1

_WELCOME_TEXT = (
    "🛡️ *Welcome to CrusaderBot*\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "Trade prediction markets with controlled risk\\.\n\n"
    "🟡 *Current Mode*\n"
    "├── PAPER only\n"
    "├── \\$1,000 demo capital\n"
    "└── Live trading locked\n\n"
    "🚀 *Setup*\n"
    "├── Choose risk preset\n"
    "├── Enable paper auto\\-trade\n"
    "└── Start signal following"
)

_MODE_TEXT = (
    "Choose your trading mode:\n\n"
    "📄 *Paper Trading* — Practice with virtual funds\\. Zero risk\\.\n"
    "💰 *Live Trading* — Real money\\. Requires setup\\."
)

_PAPER_COMPLETE_TEXT = (
    "✅ *Paper mode activated\\!*\n"
    "Starting balance: \\$10,000 virtual\n"
    "──────────────────\n"
    "Commands to get started:\n"
    "/scan — scan for opportunities\n"
    "/positions — view open trades\n"
    "/pnl — view performance\n"
    "/help — all commands"
)

_LIVE_REDIRECT_TEXT = (
    "🔒 *Live Trading Setup*\n\n"
    "Use /enable\\_live to begin the live trading setup process\\."
)


# ---------------------------------------------------------------------------
# ConversationHandler entry
# ---------------------------------------------------------------------------

async def _entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    tg_user = update.effective_user
    start_param: str | None = None
    if ctx.args:
        start_param = ctx.args[0]

    ref_code = parse_ref_param(start_param)

    user = await upsert_user(tg_user.id, tg_user.username)
    user_id = user["id"]

    await audit.write(
        actor_role="user", action="start", user_id=user_id,
        payload={"username": tg_user.username, "ref_code": ref_code},
    )

    is_new_user = not user.get("onboarding_complete", False)

    if ref_code and is_new_user:
        try:
            await record_referral(referrer_code=ref_code, referred_user_id=user_id)
        except Exception as exc:
            logger.warning("onboarding.referral_record_failed ref=%s error=%s", ref_code, exc)

    try:
        await get_or_create_referral_code(user_id)
    except Exception as exc:
        logger.warning("onboarding.referral_code_create_failed user_id=%s error=%s", user_id, exc)

    if not is_new_user:
        # Returning user — wallet should already exist but ensure safety
        wallet = await get_wallet(user_id)
        if wallet is None:
            pass  # wallet created on demand when live trading is enabled

        if has_tier(user["access_tier"], Tier.ALLOWLISTED):
            from .dashboard import dashboard
            await dashboard(update, ctx)
        else:
            await update.message.reply_text(
                "⚔️ *Welcome back to CrusaderBot\\!*\n\n"
                "Mode: 📝 Paper\n"
                "You're on the waitlist — your invite is on its way\\!",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=main_menu(),
            )
        return ConversationHandler.END

    # New user — begin onboarding
    ctx.user_data["onboard_user_id"] = str(user_id)
    await update.message.reply_text(
        _WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=get_started_kb(),
    )
    return ONBOARD_WELCOME


# ---------------------------------------------------------------------------
# Step 1 — Get Started callback
# ---------------------------------------------------------------------------

async def _get_started_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WELCOME
    await q.answer()
    await q.message.reply_text(
        _MODE_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=mode_select_kb(),
    )
    return ONBOARD_MODE


# ---------------------------------------------------------------------------
# Step 2 — Mode selection callbacks
# ---------------------------------------------------------------------------

async def _mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_MODE
    await q.answer()

    action = (q.data or "").split(":", 1)[-1]

    if action == "mode_live":
        await q.message.reply_text(
            _LIVE_REDIRECT_TEXT,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    # Paper mode
    user_id_str = ctx.user_data.get("onboard_user_id")
    if user_id_str:
        try:
            await set_onboarding_complete(UUID(user_id_str))
        except Exception as exc:
            logger.warning("onboarding.set_complete_failed user_id=%s error=%s",
                           user_id_str, exc)

    await q.message.reply_text(
        _PAPER_COMPLETE_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=paper_complete_kb(),
    )
    await q.message.reply_text("Main menu:", reply_markup=main_menu())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Standalone view-dashboard callback (outside ConversationHandler)
# ---------------------------------------------------------------------------

async def view_dashboard_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    from .dashboard import show_dashboard_for_cb
    await show_dashboard_for_cb(update, ctx)


async def onboard_settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Route ⚙️ Settings button from onboarding welcome screen."""
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    from .settings import settings_hub_root
    await settings_hub_root(update, ctx)


# ---------------------------------------------------------------------------
# ConversationHandler builder
# ---------------------------------------------------------------------------

def build_onboard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", _entry)],
        states={
            ONBOARD_WELCOME: [
                CallbackQueryHandler(
                    _get_started_cb,
                    pattern=r"^onboard:get_started$",
                ),
            ],
            ONBOARD_MODE: [
                CallbackQueryHandler(
                    _mode_cb,
                    pattern=r"^onboard:mode_(paper|live)$",
                ),
            ],
        },
        fallbacks=[CommandHandler("start", _entry)],
        per_message=False,
        allow_reentry=True,
    )


# ---------------------------------------------------------------------------
# Standalone command handlers
# ---------------------------------------------------------------------------

async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    is_op = (
        update.effective_user is not None
        and update.effective_user.id == get_settings().OPERATOR_CHAT_ID
    )

    trading = (
        "*📈 TRADING*\n"
        "/scan — scan for opportunities\n"
        "/positions — open positions with live P&L\n"
        "/close — force\\-close a position\n"
        "/pnl — performance summary\n"
    )
    portfolio = (
        "*📊 PORTFOLIO*\n"
        "/chart — portfolio chart \\(7d / 30d / all\\)\n"
        "/insights — weekly P&L breakdown\n"
        "/trades — trade history\n"
    )
    settings = (
        "*⚙️ SETTINGS*\n"
        "/mode — trading mode \\(paper / live\\)\n"
        "/referral — your referral code and stats\n"
        "/status — system health\n"
    )
    admin = (
        "*🔧 ADMIN*\n"
        "/admin — operator console\n"
        "/ops\\_dashboard — live ops plane\n"
        "/killswitch — pause all trading\n"
        "/jobs — background job status\n"
        "/auditlog — audit event log\n"
    ) if is_op else ""

    body = trading + "\n" + portfolio + "\n" + settings
    if admin:
        body += "\n" + admin

    await update.message.reply_text(
        body,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu(),
    )


async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text("Main menu:", reply_markup=main_menu())
