"""The Concierge Onboarding — progressive multi-step guided flow.

Flow for new users:
  WELCOME     → Show branded welcome card + [🚀 Get Started]
  WALLET_INIT → Credit $1,000 paper balance + show confirmation + [Continue →]
  RISK_PROFILE→ Conservative / Balanced / Aggressive picker
  DONE        → Activate scanner, show Dashboard V5

Returning users go directly to Dashboard.

Reuses existing wallet initialization and database logic.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ... import audit
from ...services.referral.referral_service import (
    get_or_create_referral_code,
    parse_ref_param,
    record_referral,
)
from ...users import set_onboarding_complete, upsert_user
from ...wallet.ledger import get_balance
from ..keyboards import main_menu
from ..roles import is_admin

logger = logging.getLogger(__name__)

# ── ConversationHandler states ────────────────────────────────────────────────
ONBOARD_WELCOME  = 0
ONBOARD_WALLET   = 1
ONBOARD_RISK     = 2
ONBOARD_DONE     = 3

_SEP = "━━━━━━━━━━━━━━━━━━━━"


# ── Step keyboards ────────────────────────────────────────────────────────────

def _welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Get Started", callback_data="onboard:start"),
    ]])


def _wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Continue →", callback_data="onboard:wallet_done"),
    ]])


def _risk_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Conservative",
                              callback_data="onboard:risk:signal_sniper")],
        [InlineKeyboardButton("⚡ Balanced  ⭐ Recommended",
                              callback_data="onboard:risk:value_hunter")],
        [InlineKeyboardButton("🚀 Aggressive",
                              callback_data="onboard:risk:full_auto")],
    ])


# ── Step texts ────────────────────────────────────────────────────────────────

_WELCOME_TEXT = (
    f"{_SEP}\n"
    "🤖  CRUSADERBOT\n"
    f"{_SEP}\n"
    "Your autonomous Polymarket trading copilot.\n\n"
    "📑 Mode: Paper  •  🟢 Status: Ready\n\n"
    "Paper trading lets you test strategies with virtual capital — no real money, no risk.\n\n"
    "Tap below to set up your account."
)

_WALLET_TEXT = (
    f"{_SEP}\n"
    "💰  PAPER WALLET INITIALIZED\n"
    f"{_SEP}\n"
    "```\n"
    "Balance  │  $1,000.00 USDC\n"
    "Mode     │  Paper (Safe)\n"
    "```\n"
    f"{_SEP}\n"
    "Your paper wallet has been credited with $1,000.\n"
    "All trades are simulated — zero financial risk."
)

_RISK_TEXT = (
    f"{_SEP}\n"
    "⚖️  CHOOSE YOUR TRADING PROFILE\n"
    f"{_SEP}\n"
    "```\n"
    "📡 Conservative\n"
    "  Risk: Low  •  Capital: up to 50%\n"
    "  Fewer trades, higher conviction.\n"
    "\n"
    "⚡ Balanced\n"
    "  Risk: Medium  •  Capital: up to 40%\n"
    "  Steady daily trades — most popular.\n"
    "\n"
    "🚀 Aggressive\n"
    "  Risk: High  •  Capital: up to 80%\n"
    "  All signals active, max opportunities.\n"
    "```\n"
    f"{_SEP}\n"
    "Choose how you want the bot to trade:"
)

_RISK_LABELS = {
    "signal_sniper": "📡 Conservative",
    "value_hunter":  "⚡ Balanced",
    "full_auto":     "🚀 Aggressive",
}


async def _done_text(user_id, risk_key: str) -> str:
    bal = await get_balance(user_id)
    label = _RISK_LABELS.get(risk_key, risk_key)
    return (
        f"{_SEP}\n"
        "✅  ALL SET — CONCIERGE COMPLETE\n"
        f"{_SEP}\n"
        "```\n"
        f"Profile  │ {label}\n"
        f"Balance  │ ${float(bal):,.2f} USDC\n"
        "Scanner  │ 🟢 Active\n"
        "```\n"
        f"{_SEP}\n"
        "📡 Scanning Polymarket for opportunities...\n\n"
        "Use the menu below to navigate."
    )


# ── Entry ─────────────────────────────────────────────────────────────────────

async def _entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    tg_user = update.effective_user
    start_param = ctx.args[0] if ctx.args else None
    ref_code    = parse_ref_param(start_param)

    user    = await upsert_user(tg_user.id, tg_user.username)
    user_id = user["id"]

    await audit.write(
        actor_role="user", action="start", user_id=user_id,
        payload={"username": tg_user.username, "ref_code": ref_code},
    )

    if ref_code and not user.get("onboarding_complete"):
        try:
            await record_referral(referrer_code=ref_code, referred_user_id=user_id)
        except Exception as exc:
            logger.warning("referral_record_failed ref=%s err=%s", ref_code, exc)

    try:
        await get_or_create_referral_code(user_id)
    except Exception as exc:
        logger.warning("referral_code_create_failed user=%s err=%s", user_id, exc)

    # ── Returning user → straight to Dashboard ────────────────────────────
    if user.get("onboarding_complete"):
        from .dashboard import dashboard
        await dashboard(update, ctx)
        return ConversationHandler.END

    # ── New user → Concierge Step 1: Welcome ─────────────────────────────
    await update.message.reply_text(
        _WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_welcome_kb(),
    )
    return ONBOARD_WELCOME


# ── Step 1 → 2: Wallet init ───────────────────────────────────────────────────

async def _start_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WELCOME
    await q.answer()

    user = await upsert_user(q.from_user.id, q.from_user.username)

    # Seed paper wallet: credit $1,000 if balance is still 0
    try:
        from ...database import get_pool
        from ...wallet.ledger import get_balance
        bal = await get_balance(user["id"])
        if float(bal) == 0.0:
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
        logger.warning("wallet_seed_failed user=%s err=%s", user["id"], exc)

    await q.message.reply_text(
        _WALLET_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_wallet_kb(),
    )
    return ONBOARD_WALLET


# ── Step 2 → 3: Risk profile ──────────────────────────────────────────────────

async def _wallet_done_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WALLET
    await q.answer()
    await q.message.reply_text(
        _RISK_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_risk_kb(),
    )
    return ONBOARD_RISK


# ── Step 3 → Done: Activate ───────────────────────────────────────────────────

async def _risk_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_RISK
    await q.answer()

    risk_key = (q.data or "").split(":")[-1]   # signal_sniper | value_hunter | full_auto

    user = await upsert_user(q.from_user.id, q.from_user.username)

    # Persist the chosen preset
    try:
        from ...users import update_settings
        await update_settings(user["id"], active_preset=risk_key)
    except Exception as exc:
        logger.warning("preset_set_failed user=%s err=%s", user["id"], exc)

    # Mark onboarding complete
    await set_onboarding_complete(user["id"])

    done_msg = await _done_text(user["id"], risk_key)
    await q.message.reply_text(
        done_msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


# ── Menu-tap fallback (exit wizard cleanly when user taps reply keyboard) ─────

async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show main menu and persistent keyboard (/menu command)."""
    if update.message is None:
        return
    await update.message.reply_text(
        "Choose an option:",
        reply_markup=main_menu(),
    )


async def view_dashboard_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """onboard:view_dashboard callback → show dashboard."""
    from .dashboard import dashboard
    q = update.callback_query
    if q:
        await q.answer()
    await dashboard(update, ctx)


async def onboard_settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """onboard:settings callback → show settings hub."""
    from .settings import settings_hub_root
    q = update.callback_query
    if q:
        await q.answer()
    await settings_hub_root(update, ctx)


async def _menu_tap_fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Exit wizard cleanly when user taps a reply keyboard button."""
    if update.message:
        from .dashboard import dashboard
        await dashboard(update, ctx)
    return ConversationHandler.END


# ── Help handler ──────────────────────────────────────────────────────────────

async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "📖 CrusaderBot Help\n\n"
        "Use the menu below to navigate:\n"
        "🤖 Auto Trade — configure your trading strategy\n"
        "💼 Portfolio  — view balance and open positions\n"
        "⚙️ Settings   — risk, mode, wallet, notifications\n"
        "📊 Insights   — your performance stats\n"
        "🛑 Stop Bot   — pause all automated trading\n\n"
        "Type /start to re-run setup at any time.",
        reply_markup=main_menu(),
    )


# ── ConversationHandler builder ───────────────────────────────────────────────

def build_onboard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", _entry)],
        states={
            ONBOARD_WELCOME: [
                CallbackQueryHandler(_start_cb, pattern=r"^onboard:start$"),
            ],
            ONBOARD_WALLET: [
                CallbackQueryHandler(_wallet_done_cb, pattern=r"^onboard:wallet_done$"),
            ],
            ONBOARD_RISK: [
                CallbackQueryHandler(_risk_cb, pattern=r"^onboard:risk:"),
            ],
        },
        fallbacks=[
            CommandHandler("start", _entry),
            MessageHandler(filters.Regex(r"^(🤖|💼|⚙️|📊|🛑)"), _menu_tap_fallback),
        ],
        per_message=False,
        allow_reentry=True,
        name="concierge_onboarding",
    )
