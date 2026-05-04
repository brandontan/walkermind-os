"""/wallet and /deposit Telegram handlers.

Surfaces:
    /wallet  — open to all tiers; shows deposit address + balance + tier label.
               Tier 1 callers see a $0.00 balance (no sub-account yet) and a
               Tier 1 label, but the address is still visible so they can
               deposit and self-promote to Tier 3.
    /deposit — Tier 2+ only (Community allowlist). Shows the deposit address
               with explicit instructions and the minimum-deposit reminder.
"""
from __future__ import annotations

import asyncpg
import structlog
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...config import Settings
from ...services.allowlist import (
    TIER_ALLOWLISTED,
    get_user_tier,
    tier_label,
)
from ...services.ledger import get_balance
from ...services.user_service import get_user_by_telegram_id
from ...wallet.vault import get_wallet
from ..middleware.tier_gate import require_tier

log = structlog.get_logger(__name__)


async def handle_wallet(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    pool: asyncpg.Pool,
    config: Settings,
) -> None:
    """Show address + USDC balance + effective tier label. Open to all tiers."""
    if update.effective_user is None or update.effective_message is None:
        return

    telegram_user_id = update.effective_user.id

    user = await get_user_by_telegram_id(pool, telegram_user_id)
    if user is None:
        await update.effective_message.reply_text(
            "👋 You haven't started yet. Send /start to register and get a deposit address."
        )
        return

    wallet = await get_wallet(pool, user["id"])
    if wallet is None:
        await update.effective_message.reply_text(
            "⚠️ Your wallet is not provisioned yet. Send /start to provision it."
        )
        return

    balance = await get_balance(pool, user["id"])

    # `users.access_tier` is the DB-backed funded tier (bumped to 3 on deposit).
    # `get_user_tier(...)` is the in-memory R3 allowlist (returns 1 or 2).
    # Effective tier shown to the user is the max of the two.
    db_tier = int(user.get("access_tier", 1))
    runtime_tier = await get_user_tier(telegram_user_id)
    effective_tier = max(db_tier, runtime_tier)

    address = wallet["deposit_address"]
    text = (
        "💰 *Wallet*\n"
        f"Address: `{address}`\n"
        f"Balance: ${balance:.2f} USDC\n"
        f"Tier: {tier_label(effective_tier)}"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@require_tier(TIER_ALLOWLISTED)
async def handle_deposit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    pool: asyncpg.Pool,
    config: Settings,
) -> None:
    """Show deposit instructions + address. Tier 2+ only (allowlisted users)."""
    if update.effective_user is None or update.effective_message is None:
        return

    telegram_user_id = update.effective_user.id

    user = await get_user_by_telegram_id(pool, telegram_user_id)
    if user is None:
        await update.effective_message.reply_text(
            "👋 You haven't started yet. Send /start to register first."
        )
        return

    wallet = await get_wallet(pool, user["id"])
    if wallet is None:
        await update.effective_message.reply_text(
            "⚠️ Your wallet is not provisioned yet. Send /start first."
        )
        return

    address = wallet["deposit_address"]
    text = (
        "Send USDC (Polygon) to:\n"
        f"`{address}`\n"
        f"Min deposit: ${config.MIN_DEPOSIT_USDC:.0f}\n"
        "Bot will confirm automatically."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
