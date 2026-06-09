"""Wallet handler — deposit instructions, balance, and withdraw flow.

Withdraw state machine (stored in ConversationHandler or user_data):
  idle → await_amount → await_address → await_confirm → idle
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...users import upsert_user
from ...wallet.ledger import get_balance
from ...wallet.vault import get_wallet
from ...wallet.withdrawals import (
    MIN_WITHDRAWAL_USDC,
    create_withdrawal_request,
    get_approval_mode,
    get_user_withdrawals,
)
from ..keyboards.wallet import (
    wallet_copy_kb,
    wallet_deposit_kb,
    wallet_home_kb,
    withdraw_cancel_kb,
    withdraw_confirm_kb,
    withdraw_history_kb,
)
from ..messages import (
    admin_withdrawal_item_text,
    wallet_deposit_text,
    wallet_text,
    withdraw_ask_address_text,
    withdraw_ask_amount_text,
    withdraw_confirm_text,
    withdraw_history_text,
    withdraw_submitted_text,
)
from ... import notifications
from ..ui.tree import md_v2_escape as _md

logger = logging.getLogger(__name__)

# ConversationHandler states
_AWAIT_AMOUNT, _AWAIT_ADDRESS = range(2)

_ETH_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_user_and_wallet(update: Update) -> tuple | None:
    if update.effective_user is None:
        return None
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    w = await get_wallet(user["id"])
    return user, w


async def _edit_or_reply(
    update: Update,
    text: str,
    reply_markup=None,
) -> None:
    kwargs: dict = {"parse_mode": ParseMode.MARKDOWN_V2}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    q = update.callback_query
    if q is not None and q.message is not None:
        try:
            await q.edit_message_text(text, **kwargs)
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                await q.message.reply_text(text, **kwargs)
    elif update.message is not None:
        await update.message.reply_text(text, **kwargs)


# ── wallet home ───────────────────────────────────────────────────────────────

async def _render_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    result = await _get_user_and_wallet(update)
    if result is None:
        return
    user, w = result
    address = w["deposit_address"] if w else "(not set)"
    balance = await get_balance(user["id"])
    text = wallet_text(balance, address)
    await _edit_or_reply(update, text, wallet_home_kb())


async def wallet_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_home(update, ctx)


async def wallet_root_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    await _render_home(update, ctx)


# ── deposit screen ────────────────────────────────────────────────────────────

async def _render_deposit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    result = await _get_user_and_wallet(update)
    if result is None:
        return
    user, w = result
    address = w["deposit_address"] if w else "(not set)"
    balance = await get_balance(user["id"])
    text = wallet_deposit_text(address, balance)
    await _edit_or_reply(update, text, wallet_deposit_kb())


# ── copy address ──────────────────────────────────────────────────────────────

async def _handle_copy(update: Update) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    result = await _get_user_and_wallet(update)
    if result is None:
        return
    _, w = result
    address = w["deposit_address"] if w else "(not set)"
    if address != "(not set)":
        await q.answer(f"Address: {address}", show_alert=True)
    else:
        await q.answer("Address not available yet.", show_alert=True)


# ── withdraw history ──────────────────────────────────────────────────────────

async def _render_withdraw_history(update: Update) -> None:
    result = await _get_user_and_wallet(update)
    if result is None:
        return
    user, _ = result
    withdrawals = await get_user_withdrawals(user["id"])
    text = withdraw_history_text(withdrawals)
    await _edit_or_reply(update, text, withdraw_history_kb())


# ── main callback router ──────────────────────────────────────────────────────

async def wallet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "home":
        await _render_home(update, ctx)
    elif sub == "deposit":
        await _render_deposit(update, ctx)
    elif sub.startswith("balance"):
        await _render_home(update, ctx)
    elif sub == "copy":
        await _handle_copy(update)
    elif sub == "withdraw":
        await _start_withdraw(update, ctx)
    elif sub.startswith("withdraw_confirm:"):
        await _process_withdraw_confirm(update, ctx, sub)
    elif sub == "withdraw_history":
        await _render_withdraw_history(update)
    else:
        await _render_home(update, ctx)


# ── withdraw flow (inline — no ConversationHandler dependency) ────────────────
# State is stored in ctx.user_data under key "_wd" (withdraw draft).

async def _start_withdraw(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    result = await _get_user_and_wallet(update)
    if result is None:
        return
    user, _ = result
    balance = await get_balance(user["id"])
    if balance < MIN_WITHDRAWAL_USDC:
        await _edit_or_reply(
            update,
            f"*Insufficient balance*\n\nMinimum withdrawal: `${MIN_WITHDRAWAL_USDC}`\n"
            f"Your balance: `{balance:.2f} USDC`",
            withdraw_cancel_kb(),
        )
        return
    ctx.user_data["_wd"] = {"step": "amount", "balance": str(balance)}
    await _edit_or_reply(
        update,
        withdraw_ask_amount_text(balance),
        withdraw_cancel_kb(),
    )


async def handle_withdraw_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles free-text input for the withdraw flow.

    Called only if _wd draft is in progress; ignored otherwise.
    """
    wd = ctx.user_data.get("_wd")
    if wd is None or update.message is None or update.effective_user is None:
        return

    text = (update.message.text or "").strip()

    if wd["step"] == "amount":
        try:
            amount = Decimal(text.replace("$", "").replace(",", ""))
        except InvalidOperation:
            await update.message.reply_text(
                "Invalid amount\\. Enter a number like `25.00`",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=withdraw_cancel_kb(),
            )
            return
        balance = Decimal(wd["balance"])
        if amount < MIN_WITHDRAWAL_USDC:
            await update.message.reply_text(
                f"Minimum withdrawal is `${MIN_WITHDRAWAL_USDC}`",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=withdraw_cancel_kb(),
            )
            return
        if amount > balance:
            await update.message.reply_text(
                f"Insufficient balance\\. Available: `${balance:.2f}`",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=withdraw_cancel_kb(),
            )
            return
        wd["amount"] = str(amount)
        wd["step"] = "address"
        await update.message.reply_text(
            withdraw_ask_address_text(str(amount)),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=withdraw_cancel_kb(),
        )

    elif wd["step"] == "address":
        if not _ETH_ADDR_RE.match(text):
            await update.message.reply_text(
                "Invalid Polygon address\\. Must start with `0x` followed by 40 hex chars\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=withdraw_cancel_kb(),
            )
            return
        wd["address"] = text
        wd["step"] = "confirm"
        await update.message.reply_text(
            withdraw_confirm_text(wd["amount"], text),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=withdraw_confirm_kb(wd["amount"], text),
        )


async def _process_withdraw_confirm(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    sub: str,
) -> None:
    """Handles wallet:withdraw_confirm:{amount}:{address} callback."""
    # sub format: withdraw_confirm:{amount}:{address}
    parts = sub.split(":", 2)
    if len(parts) < 3:
        await _render_home(update, ctx)
        return
    _, amount_str, address = parts

    if not _ETH_ADDR_RE.match(address):
        await _edit_or_reply(update, "⚠️ Invalid address in confirmation\\.", withdraw_cancel_kb())
        return

    result = await _get_user_and_wallet(update)
    if result is None:
        return
    user, _ = result

    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        await _edit_or_reply(update, "⚠️ Invalid amount\\.", withdraw_cancel_kb())
        return

    balance = await get_balance(user["id"])
    if amount > balance:
        await _edit_or_reply(
            update,
            f"⚠️ Insufficient balance\\.\nAvailable: `${balance:.2f}`\nRequested: `${amount:.2f}`",
            withdraw_cancel_kb(),
        )
        return

    try:
        w = await create_withdrawal_request(user["id"], amount, address)
    except Exception as exc:
        logger.error("withdraw create failed: %s", exc)
        await _edit_or_reply(update, f"❌ Withdrawal failed: {_md(str(exc))}", withdraw_cancel_kb())
        return

    # Clear draft
    ctx.user_data.pop("_wd", None)

    mode = w["approval_mode"]
    await _edit_or_reply(
        update,
        withdraw_submitted_text(amount_str, mode),
        withdraw_history_kb(),
    )

    # Notify operator if manual approval required
    if mode == "manual":
        from ...wallet.withdrawals import get_pending_withdrawals
        w_with_user = {**w, "telegram_id": update.effective_user.id,
                       "username": update.effective_user.username or ""}
        op_text = (
            "🔔 *New Withdrawal Request*\n\n"
            + admin_withdrawal_item_text(w_with_user)
            + "\n\nUse /admin withdrawals to manage\\."
        )
        try:
            from telegram.constants import ParseMode as _PM
            await notifications.notify_operator(op_text, parse_mode=_PM.MARKDOWN_V2)
        except Exception as exc:
            logger.warning("Failed to notify operator of withdrawal: %s", exc)
