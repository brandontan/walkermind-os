"""/start onboarding — creates user, derives wallet, shows main menu."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ... import audit
from ...users import upsert_user
from ...wallet.vault import create_wallet_for_user, get_wallet
from ..keyboards import main_menu

logger = logging.getLogger(__name__)


async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    tg_user = update.effective_user
    user = await upsert_user(tg_user.id, tg_user.username)
    wallet = await get_wallet(user["id"])
    if wallet is None:
        addr, idx = await create_wallet_for_user(user["id"])
        wallet = {"deposit_address": addr, "hd_index": idx}
        await audit.write(actor_role="user", action="wallet_created",
                          user_id=user["id"],
                          payload={"hd_index": idx, "address": addr})

    text = (
        f"⚔️ *Welcome to CrusaderBot, {tg_user.first_name or 'user'}!*\n\n"
        "Autonomous Polymarket trading. Telegram-controlled. Safety-first.\n\n"
        "*Your USDC deposit address (Polygon):*\n"
        f"`{wallet['deposit_address']}`\n"
        "_(tap to copy)_\n\n"
        f"*Tier:* {user['access_tier']} — "
        f"{'Browse' if user['access_tier'] == 1 else 'Allowlisted' if user['access_tier'] == 2 else 'Funded' if user['access_tier'] == 3 else 'Live'}\n\n"
        "Send USDC on Polygon to the address above to unlock paper trading. "
        "Use the menu below to configure your strategy."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu(),
    )
    await audit.write(actor_role="user", action="start", user_id=user["id"],
                      payload={"username": tg_user.username})


async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "*CrusaderBot commands*\n\n"
        "/start — onboarding / main menu\n"
        "/menu — show main menu\n"
        "/dashboard — current status & PnL\n"
        "/positions — open positions\n"
        "/activity — recent trades\n"
        "/emergency — pause / close all\n"
        "/admin — operator controls (operator only)\n",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu(),
    )


async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text("Main menu:", reply_markup=main_menu())
