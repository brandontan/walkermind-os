"""The Concierge Onboarding — progressive multi-step guided flow.

Flow for new users:
  WELCOME      → Show branded welcome card + [🚀 Get Started]
  WALLET_INIT  → Credit $1,000 paper balance, edit card + [Continue →]
  RISK_PROFILE → Conservative / Balanced / Aggressive picker, edit card
  DONE         → Mark complete, show main menu + reply keyboard

Returning users go directly to Dashboard.
"""
from __future__ import annotations

import html
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
from ...domain.preset.presets import capital_for_risk_profile
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
                              callback_data="onboard:risk:conservative")],
        [InlineKeyboardButton("⚡ Balanced  ⭐ Recommended",
                              callback_data="onboard:risk:balanced")],
        [InlineKeyboardButton("🚀 Aggressive",
                              callback_data="onboard:risk:aggressive")],
    ])


# ── Step texts ────────────────────────────────────────────────────────────────

_WELCOME_TEXT = (
    "<b>🤖 CRUSADERBOT</b>\n"
    "Your autonomous Polymarket trading copilot.\n\n"
    "<blockquote>📑 Mode: Paper  •  🟢 Status: Ready</blockquote>\n\n"
    "Paper trading lets you test strategies with virtual capital — no real money, no risk.\n\n"
    "Tap below to set up your account."
)

_WALLET_TEXT = (
    "<b>💰 PAPER WALLET INITIALIZED</b>\n\n"
    "<blockquote>"
    "Balance  $1,000.00 USDC\n"
    "Mode     Paper (Safe)"
    "</blockquote>\n\n"
    "Your paper wallet has been credited with $1,000.\n"
    "All trades are simulated — zero financial risk."
)

_RISK_TEXT = (
    "<b>⚖️ CHOOSE YOUR TRADING PROFILE</b>\n\n"
    "<blockquote>"
    "📡 Conservative\n"
    "Risk: Low  •  Capital: 20%\n"
    "Fewer trades, higher conviction.\n"
    "\n"
    "⚡ Balanced\n"
    "Risk: Medium  •  Capital: 40%\n"
    "Steady daily trades — most popular.\n"
    "\n"
    "🚀 Aggressive\n"
    "Risk: High  •  Capital: 60%\n"
    "All signals active, max opportunities."
    "</blockquote>\n\n"
    "Choose how you want the bot to trade:"
)

_RISK_LABELS = {
    "conservative": "📡 Conservative",
    "balanced":     "⚡ Balanced",
    "aggressive":   "🚀 Aggressive",
}


async def _done_text(user_id, risk_profile: str) -> str:
    bal = await get_balance(user_id)
    label = html.escape(_RISK_LABELS.get(risk_profile, risk_profile))
    capital_pct = int(capital_for_risk_profile(risk_profile) * 100)
    return (
        "<b>✅ ALL SET — CONCIERGE COMPLETE</b>\n\n"
        "<blockquote>"
        f"Profile  {label}\n"
        f"Capital  {capital_pct}% per trade\n"
        f"Balance  ${float(bal):,.2f} USDC\n"
        "Scanner  🟢 Active"
        "</blockquote>\n\n"
        "📡 Scanning Polymarket for opportunities…\n\n"
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

    # ── New user → Step 1: Welcome ────────────────────────────────────────
    msg = await update.message.reply_text(
        _WELCOME_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=_welcome_kb(),
    )
    ctx.user_data["onboard_msg_id"] = msg.message_id
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

    await q.edit_message_text(
        _WALLET_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=_wallet_kb(),
    )
    return ONBOARD_WALLET


# ── Step 2 → 3: Risk profile ──────────────────────────────────────────────────

async def _wallet_done_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WALLET
    await q.answer()
    await q.edit_message_text(
        _RISK_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=_risk_kb(),
    )
    return ONBOARD_RISK


# ── Step 3 → Done: Activate ───────────────────────────────────────────────────

async def _risk_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_RISK
    await q.answer()

    risk_profile = (q.data or "").split(":")[-1]   # conservative | balanced | aggressive

    user = await upsert_user(q.from_user.id, q.from_user.username)

    # Persist risk profile and capital allocation
    try:
        from ...users import update_settings
        capital_pct = capital_for_risk_profile(risk_profile)
        await update_settings(
            user["id"],
            risk_profile=risk_profile,
            capital_alloc_pct=capital_pct,
        )
    except Exception as exc:
        logger.warning("risk_profile_set_failed user=%s err=%s", user["id"], exc)

    await set_onboarding_complete(user["id"])

    done_msg = await _done_text(user["id"], risk_profile)
    await q.edit_message_text(
        done_msg,
        parse_mode=ParseMode.HTML,
    )
    await q.message.reply_text(
        "Use the buttons below to navigate.",
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
        "<b>📖 CrusaderBot Help</b>\n\n"
        "Use the menu below to navigate:\n"
        "📊 Dashboard   — account overview and status\n"
        "🤖 Auto-Trade  — configure your trading strategy\n"
        "💼 Portfolio   — view balance and open positions\n"
        "📈 My Trades   — open positions and trade history\n"
        "⚙️ Settings    — risk, mode, wallet, notifications\n"
        "🚨 Emergency   — pause or lock trading immediately\n\n"
        "Type /start to re-run setup at any time.",
        parse_mode=ParseMode.HTML,
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
            MessageHandler(filters.TEXT & ~filters.COMMAND, _menu_tap_fallback),
        ],
        per_message=False,
        allow_reentry=True,
        name="concierge_onboarding",
    )
