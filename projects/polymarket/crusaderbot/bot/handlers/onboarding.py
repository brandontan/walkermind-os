"""/start onboarding — creates user, derives wallet, shows main menu."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ... import audit
from ...users import get_user_by_telegram_id, upsert_user
from ...wallet.vault import create_wallet_for_user, get_wallet
from ..keyboards import main_menu
from ..tier import Tier, has_tier

logger = logging.getLogger(__name__)


async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    tg_user = update.effective_user

    existing = await get_user_by_telegram_id(tg_user.id)
    user = await upsert_user(tg_user.id, tg_user.username)

    wallet = await get_wallet(user["id"])
    if wallet is None:
        addr, idx = await create_wallet_for_user(user["id"])
        wallet = {"deposit_address": addr, "hd_index": idx}
        await audit.write(actor_role="user", action="wallet_created",
                          user_id=user["id"],
                          payload={"hd_index": idx, "address": addr})

    await audit.write(actor_role="user", action="start", user_id=user["id"],
                      payload={"username": tg_user.username})

    if existing is not None and has_tier(user["access_tier"], Tier.ALLOWLISTED):
        from .dashboard import dashboard
        await dashboard(update, ctx)
        return

    tier_label = (
        "Browse" if user["access_tier"] == 1
        else "Allowlisted" if user["access_tier"] == 2
        else "Funded" if user["access_tier"] == 3
        else "Live"
    )
    text = (
        f"⚔️ *Welcome to CrusaderBot, {tg_user.first_name or 'user'}!*\n\n"
        "An autonomous Polymarket trading service, controlled via Telegram. "
        "📄 *Currently in paper-trading mode — no real capital is deployed.*\n\n"
        "*Next steps:*\n"
        "• /about — what CrusaderBot does, in plain English\n"
        "• /demo — see live signals the bot is watching right now\n"
        "• /status — health check, version, current mode\n\n"
        "*Your USDC deposit address (Polygon):*\n"
        f"`{wallet['deposit_address']}`\n"
        "_(tap to copy — funding unlocks paper trading once allowlisted)_\n\n"
        f"*Tier:* {user['access_tier']} — {tier_label}\n\n"
        "Use the menu below to explore the bot."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu(),
    )


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
