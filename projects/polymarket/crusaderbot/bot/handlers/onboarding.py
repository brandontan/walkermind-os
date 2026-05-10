"""First-time onboarding flow + returning-user /start routing."""
from __future__ import annotations

import io
import logging
from uuid import UUID

import qrcode
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from ... import audit
from ...users import get_user_by_telegram_id, set_onboarding_complete, upsert_user
from ...wallet.vault import create_wallet_for_user, get_wallet
from ..keyboards import main_menu
from ..keyboards.onboarding import (
    deposit_kb,
    faq_kb,
    style_picker_kb,
    wallet_kb,
    welcome_kb,
)
from ..tier import Tier, has_tier

logger = logging.getLogger(__name__)

# ConversationHandler state constants
ONBOARD_WELCOME = 0
ONBOARD_FAQ = 1
ONBOARD_WALLET = 2
ONBOARD_STYLE = 3
ONBOARD_DEPOSIT = 4

_WELCOME_TEXT = (
    "⚔️ *Welcome to CrusaderBot*\n\n"
    "Your autonomous Polymarket trading bot\\.\n\n"
    "Here is how it works:\n"
    "1\\. We create a wallet for you\n"
    "2\\. You pick a trading style\n"
    "3\\. Bot trades for you 24/7\n\n"
    "Ready to get started?"
)

_FAQ_TEXT = (
    "ℹ️ *Frequently Asked Questions*\n\n"
    "*What is Polymarket?*\n"
    "A prediction market where you trade on real\\-world outcomes — "
    "elections, sports, crypto, and more\\.\n\n"
    "*How does copy trade work?*\n"
    "We monitor top Polymarket wallets\\. When they trade, CrusaderBot "
    "mirrors their position for you — automatically, in real time\\.\n\n"
    "*Is my money safe?*\n"
    "CrusaderBot runs in paper\\-trading mode by default — no real capital "
    "is deployed until you enable live mode\\. Your keys are encrypted and "
    "only you control your funds\\.\n\n"
    "*What are paper trades?*\n"
    "Simulated trades using virtual capital that track real market prices\\. "
    "Test the bot risk\\-free before going live\\."
)

_STYLE_TEXT = (
    "🎯 *How do you want to trade?*\n\n"
    "🐋 *Copy Trade* — Follow top wallets\\. Their trades \\= your trades\\.\n"
    "🤖 *Auto Trade* — Bot decides using signals and edge models\\.\n"
    "⚡ *Both* — Copy Trade \\+ Auto Trade combined\\."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_qr_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _short_addr(addr: str) -> str:
    if len(addr) < 10:
        return addr
    return f"{addr[:6]}...{addr[-3:]}"


# ---------------------------------------------------------------------------
# ConversationHandler entry
# ---------------------------------------------------------------------------

async def _entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    tg_user = update.effective_user
    user = await upsert_user(tg_user.id, tg_user.username)
    await audit.write(
        actor_role="user", action="start", user_id=user["id"],
        payload={"username": tg_user.username},
    )

    if user.get("onboarding_complete", False):
        # Returning user — wallet should already exist but ensure safety
        wallet = await get_wallet(user["id"])
        if wallet is None:
            await create_wallet_for_user(user["id"])

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
    ctx.user_data["onboard_user_id"] = str(user["id"])
    await update.message.reply_text(
        _WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=welcome_kb(),
    )
    return ONBOARD_WELCOME


# ---------------------------------------------------------------------------
# Step 1 — Welcome callbacks
# ---------------------------------------------------------------------------

async def _welcome_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WELCOME
    await q.answer()

    action = (q.data or "").split(":", 1)[-1]

    if action == "learn_more":
        await q.message.reply_text(
            _FAQ_TEXT,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=faq_kb(),
        )
        return ONBOARD_FAQ

    # Let's Go — check wallet
    user_id_str = ctx.user_data.get("onboard_user_id")
    if not user_id_str:
        return ConversationHandler.END

    user_id = UUID(user_id_str)
    wallet = await get_wallet(user_id)

    if wallet is not None:
        # Wallet exists — skip to style picker
        ctx.user_data["onboard_addr"] = wallet["deposit_address"]
        await q.message.reply_text(
            _STYLE_TEXT,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=style_picker_kb(),
        )
        return ONBOARD_STYLE

    # Create wallet
    await q.message.reply_text("⏳ Creating your wallet\\.\\.\\.",
                                parse_mode=ParseMode.MARKDOWN_V2)
    addr, idx = await create_wallet_for_user(user_id)
    ctx.user_data["onboard_addr"] = addr
    await audit.write(
        actor_role="user", action="wallet_created_onboarding",
        user_id=user_id, payload={"hd_index": idx, "address": addr},
    )
    short = _short_addr(addr)
    await q.message.reply_text(
        f"✅ *Wallet ready:* `{short}`\n\n"
        "Send USDC \\(Polygon\\) to this address to fund your account\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=wallet_kb(),
    )
    return ONBOARD_WALLET


# ---------------------------------------------------------------------------
# Step FAQ callbacks
# ---------------------------------------------------------------------------

async def _faq_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_FAQ
    await q.answer()
    await q.message.reply_text(
        _WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=welcome_kb(),
    )
    return ONBOARD_WELCOME


# ---------------------------------------------------------------------------
# Step 2 — Wallet callbacks
# ---------------------------------------------------------------------------

async def _wallet_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WALLET
    await q.answer()

    action = (q.data or "").split(":", 1)[-1]
    addr = ctx.user_data.get("onboard_addr", "")

    if action == "copy_addr":
        await q.message.reply_text(
            f"📋 *Your deposit address:*\n`{addr}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ONBOARD_WALLET

    # Next → style picker
    await q.message.reply_text(
        _STYLE_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=style_picker_kb(),
    )
    return ONBOARD_STYLE


# ---------------------------------------------------------------------------
# Step 3 — Style picker callbacks
# ---------------------------------------------------------------------------

async def _style_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_STYLE
    await q.answer()

    # data format: "onboard:style:copy_trade" / "auto_trade" / "both"
    parts = (q.data or "").split(":", 2)
    style = parts[2] if len(parts) == 3 else ""
    ctx.user_data["onboard_style"] = style

    addr = ctx.user_data.get("onboard_addr", "")
    short = _short_addr(addr) if addr else "\\(not set\\)"
    await q.message.reply_text(
        "💰 *Deposit USDC \\(Polygon\\) to start trading\\.*\n"
        "Minimum deposit: \\$50\n\n"
        f"Your address: `{short}`",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=deposit_kb(),
    )
    return ONBOARD_DEPOSIT


# ---------------------------------------------------------------------------
# Step 4 — Deposit prompt callbacks
# ---------------------------------------------------------------------------

async def _deposit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_DEPOSIT
    await q.answer()

    action = (q.data or "").split(":", 1)[-1]
    addr = ctx.user_data.get("onboard_addr", "")

    if action == "qr":
        qr_bytes = _make_qr_bytes(addr)
        await q.message.reply_photo(
            photo=qr_bytes,
            caption=f"📷 Scan to deposit USDC \\(Polygon\\)\n`{addr}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ONBOARD_DEPOSIT

    if action == "deposit_copy":
        await q.message.reply_text(
            f"📋 *Full deposit address:*\n`{addr}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ONBOARD_DEPOSIT

    # Skip — mark complete and land on dashboard
    user_id_str = ctx.user_data.get("onboard_user_id")
    if user_id_str:
        await set_onboarding_complete(UUID(user_id_str))

    style = ctx.user_data.get("onboard_style", "")
    if style == "copy_trade":
        tip = "Tap 🐋 *Copy Trade* to add your first wallet to follow\\!"
    elif style == "auto_trade":
        tip = "Tap 🤖 *Auto\\-Trade* to configure your strategy\\!"
    elif style == "both":
        tip = (
            "Start with 🤖 *Auto\\-Trade* to set your strategy, "
            "then add 🐋 *Copy Trade* wallets\\!"
        )
    else:
        tip = "Use the menu below to explore the bot\\."

    await q.message.reply_text(
        "🎉 *You're all set\\!*\n\n"
        "Mode: 📝 *Paper* — no real capital deployed\\.\n\n"
        f"{tip}",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ConversationHandler builder
# ---------------------------------------------------------------------------

def build_onboard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", _entry)],
        states={
            ONBOARD_WELCOME: [
                CallbackQueryHandler(
                    _welcome_cb,
                    pattern=r"^onboard:(lets_go|learn_more)$",
                ),
            ],
            ONBOARD_FAQ: [
                CallbackQueryHandler(_faq_cb, pattern=r"^onboard:got_it$"),
            ],
            ONBOARD_WALLET: [
                CallbackQueryHandler(
                    _wallet_cb,
                    pattern=r"^onboard:(copy_addr|next)$",
                ),
            ],
            ONBOARD_STYLE: [
                CallbackQueryHandler(
                    _style_cb,
                    pattern=r"^onboard:style:(copy_trade|auto_trade|both)$",
                ),
            ],
            ONBOARD_DEPOSIT: [
                CallbackQueryHandler(
                    _deposit_cb,
                    pattern=r"^onboard:(qr|deposit_copy|skip)$",
                ),
            ],
        },
        fallbacks=[CommandHandler("start", _entry)],
        per_message=False,
        allow_reentry=True,
    )


# ---------------------------------------------------------------------------
# Standalone command handlers (unchanged)
# ---------------------------------------------------------------------------

async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "*CrusaderBot — command reference*\n\n"
        "*📱 Main Menu*\n"
        "📊 Dashboard — balance, P&L, auto-trade toggle\n"
        "🤖 Auto-Trade — strategy, risk, TP/SL, mode setup\n"
        "💰 Wallet — deposit, balance, withdraw\n"
        "📈 My Trades — open positions + recent activity\n"
        "🚨 Emergency — pause, resume, or close all\n\n"
        "*🔍 Demo*\n"
        "/about — what CrusaderBot is, in plain English\n"
        "/demo — preview live signals (rate-limited)\n"
        "/status — health, version, paper-mode indicator\n\n"
        "*🎯 Strategy*\n"
        "/copytrade — copy-trade strategy controls\n"
        "/signals — operator signal feeds\n"
        "/live\\_checklist — pre-flight before live mode\n\n"
        "*👤 Account*\n"
        "/start — onboarding / main menu\n"
        "/menu — show main menu\n"
        "/settings — account settings (auto-redeem, etc.)\n"
        "/dashboard — balance, P&L, exposure\n"
        "/positions — open positions with live P&L + force-close\n"
        "/activity — recent trades\n"
        "/summary\\_on, /summary\\_off — daily P&L digest\n"
        "/emergency — pause or close all\n\n"
        "*🛠️ Operator*\n"
        "/admin, /allowlist — operator controls\n"
        "/ops\\_dashboard, /jobs, /auditlog — ops plane\n"
        "/killswitch, /kill, /resume — pause / resume trading\n",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu(),
    )


async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text("Main menu:", reply_markup=main_menu())
