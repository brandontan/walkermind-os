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
    try:
        existing = await get_wallet(pool, user_id)
    except Exception as exc:
        log.error(
            "handle_start.wallet_lookup_failed",
            user_id=str(user_id),
            error=str(exc),
        )
        await update.effective_message.reply_text(
            "⚠️ Could not load your wallet. Please try /start again."
        )
        return

    if existing is None:
        # MAX(hd_index)+1 is read outside the INSERT, so two concurrent /start
        # callers can pick the same index. UNIQUE(hd_index) catches the race;
        # we retry up to 3x with a fresh index. Only hd_index conflicts retry —
        # user_id / deposit_address conflicts indicate a real bug and surface as failure.
        max_attempts = 3
        address: str | None = None
        for attempt in range(1, max_attempts + 1):
            hd_index = await get_next_hd_index(pool)
            address, private_key = derive_address(
                config.WALLET_HD_SEED, hd_index
            )
            encrypted = encrypt_pk(private_key, config.WALLET_ENCRYPTION_KEY)
            # Drop the cleartext key from this scope before any further await.
            private_key = ""
            del private_key
            try:
                await store_wallet(pool, user_id, address, hd_index, encrypted)
                log.info(
                    "wallet.provisioned",
                    user_id=str(user_id),
                    hd_index=hd_index,
                    address=address,
                    attempt=attempt,
                )
                break
            except asyncpg.UniqueViolationError as exc:
                constraint = exc.constraint_name or ""
                # Both hd_index and deposit_address conflicts are surfaces of the
                # same underlying allocator race: two callers picked the same
                # hd_index (the second insert collides on whichever unique index
                # Postgres checks first). Retry re-allocates a fresh hd_index
                # which derives a different address, so both paths recover.
                if "hd_index" in constraint or "deposit_address" in constraint:
                    log.warning(
                        "wallet.provision_allocator_race",
                        user_id=str(user_id),
                        hd_index=hd_index,
                        attempt=attempt,
                        constraint=constraint,
                    )
                    if attempt == max_attempts:
                        log.error(
                            "wallet.provision_max_retries_exceeded",
                            user_id=str(user_id),
                            attempts=max_attempts,
                        )
                        await update.effective_message.reply_text(
                            "⚠️ Wallet setup failed after retries. Please try /start again."
                        )
                        return
                    continue
                # PK on user_id (wallets_pkey): a concurrent /start for THIS user
                # has already provisioned. Idempotent recovery — re-fetch the
                # winning wallet and surface its address rather than a false error.
                race_winner = await get_wallet(pool, user_id)
                if race_winner is not None:
                    address = race_winner["deposit_address"]
                    log.info(
                        "wallet.race_resolved_idempotent",
                        user_id=str(user_id),
                        constraint=constraint,
                        address=address,
                    )
                    break
                # Unique conflict but no wallet for this user — genuine defect.
                log.error(
                    "wallet.provision_unique_violation",
                    user_id=str(user_id),
                    constraint=constraint,
                    error=str(exc),
                )
                await update.effective_message.reply_text(
                    "⚠️ Wallet setup failed. Please try /start again."
                )
                return
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
