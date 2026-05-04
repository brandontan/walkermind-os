"""Onboarding flow: /start handler — user upsert + HD wallet provisioning."""
from __future__ import annotations

import asyncpg
import structlog
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...config import Settings
from ...services.user_service import get_or_create_user
from ...wallet.generator import derive_address, encrypt_pk
from ...wallet.vault import get_next_hd_index, get_wallet, store_wallet

log = structlog.get_logger(__name__)


async def handle_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    pool: asyncpg.Pool,
    config: Settings,
) -> None:
    """Handle /start: upsert user, provision HD wallet on first contact, reply with deposit address.

    Idempotent: subsequent /start calls return the existing wallet without provisioning a new one.
    Private keys are encrypted at rest and never appear in any log line or Telegram reply.
    """
    if update.effective_user is None or update.effective_message is None:
        return

    telegram_user_id = update.effective_user.id
    username = update.effective_user.username

    try:
        user = await get_or_create_user(pool, telegram_user_id, username)
    except Exception as exc:
        log.error(
            "handle_start.user_upsert_failed",
            telegram_user_id=telegram_user_id,
            error=str(exc),
        )
        await update.effective_message.reply_text(
            "⚠️ Could not register your account. Please try again later."
        )
        return

    user_id = user["id"]
    existing = await get_wallet(pool, user_id)

    if existing is None:
        try:
            hd_index = await get_next_hd_index(pool)
            address, private_key = derive_address(
                config.WALLET_HD_SEED, hd_index
            )
            encrypted = encrypt_pk(private_key, config.WALLET_ENCRYPTION_KEY)
            # Drop the cleartext key from this scope before any further await.
            private_key = ""
            del private_key
            await store_wallet(pool, user_id, address, hd_index, encrypted)
            log.info(
                "wallet.provisioned",
                user_id=str(user_id),
                hd_index=hd_index,
                address=address,
            )
        except Exception as exc:
            log.error(
                "handle_start.wallet_provision_failed",
                user_id=str(user_id),
                error=str(exc),
            )
            await update.effective_message.reply_text(
                "⚠️ Wallet setup failed. Please try /start again."
            )
            return
    else:
        address = existing["deposit_address"]
        log.info(
            "wallet.exists",
            user_id=str(user_id),
            address=address,
        )

    reply = (
        "👋 Welcome to CrusaderBot!\n"
        "📄 Paper mode active — no real money at risk.\n"
        "\n"
        "💳 Your deposit address:\n"
        f"`{address}` (tap to copy)\n"
        "\n"
        "Send USDC on Polygon to this address to fund your account.\n"
        f"Minimum deposit: ${config.MIN_DEPOSIT_USDC:.0f}\n"
        "\n"
        "Use /menu to explore features."
    )
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
