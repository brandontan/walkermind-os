"""Wallet menu: deposit address / balance / withdraw stub."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...integrations.polygon import get_native_balance, get_usdc_balance
from ...users import upsert_user
from ...wallet.ledger import get_balance
from ...wallet.vault import get_wallet
from ..keyboards import wallet_menu


async def wallet_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    w = await get_wallet(user["id"])
    addr = w["deposit_address"] if w else "(not set)"
    await update.message.reply_text(
        f"*💰 Wallet*\n\nDeposit address (Polygon USDC):\n`{addr}`\n\n"
        "Tap an option below.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=wallet_menu(),
    )


async def wallet_root_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback-query-compatible entry point for the wallet surface."""
    q = update.callback_query
    if q is None or q.message is None or update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    w = await get_wallet(user["id"])
    addr = w["deposit_address"] if w else "(not set)"
    await q.message.reply_text(
        f"*💰 Wallet*\n\nDeposit address (Polygon USDC):\n`{addr}`\n\n"
        "Tap an option below.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=wallet_menu(),
    )


async def wallet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    w = await get_wallet(user["id"])
    addr = w["deposit_address"] if w else "(not set)"
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "deposit":
        await q.message.reply_text(
            f"*📥 Deposit USDC on Polygon*\n\n`{addr}`\n_(tap to copy)_\n\n"
            "Send any amount of USDC (Polygon mainnet, contract "
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174). "
            "We confirm and credit you within ~2 minutes.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "balance":
        ledger_bal = await get_balance(user["id"])
        on_chain = await get_usdc_balance(addr) if w else 0.0
        matic = await get_native_balance(addr) if w else 0.0
        await q.message.reply_text(
            f"*💵 Balance*\n\n"
            f"Ledger (tradable): *${ledger_bal:.2f}* USDC\n"
            f"On-chain (deposit address): {on_chain:.4f} USDC · {matic:.4f} MATIC",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "withdraw":
        await q.message.reply_text(
            "*📤 Withdraw* (manual gate — MVP)\n\n"
            "Withdrawals are processed manually during MVP. "
            "Please contact the operator with your desired amount and destination "
            "address. You'll receive confirmation within 24 hours.",
            parse_mode=ParseMode.MARKDOWN,
        )
