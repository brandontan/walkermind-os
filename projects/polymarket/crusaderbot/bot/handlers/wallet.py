"""Phase 5 UX Rebuild — Wallet screen."""
from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...users import upsert_user
from ...wallet.ledger import get_balance
from ...wallet.vault import get_wallet
from ..keyboards import wallet_p5_kb
from ..messages import wallet_text

logger = logging.getLogger(__name__)


async def _render(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    w = await get_wallet(user["id"])
    address = w["deposit_address"] if w else "(not set)"
    balance = await get_balance(user["id"])
    text = wallet_text(balance, address)
    kb = wallet_p5_kb()

    q = update.callback_query
    if q is not None and q.message is not None:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def wallet_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _render(update, ctx)


async def wallet_root_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _render(update, ctx)


async def wallet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "copy":
        user = await upsert_user(update.effective_user.id, update.effective_user.username)
        w = await get_wallet(user["id"])
        address = w["deposit_address"] if w else "(not set)"
        if address != "(not set)":
            await q.answer(f"Address: {address}", show_alert=True)
        else:
            await q.answer("Address not available yet.", show_alert=True)
        return

    # All other p5:wallet:* sub-routes re-render the wallet screen
    await _render(update, ctx)
