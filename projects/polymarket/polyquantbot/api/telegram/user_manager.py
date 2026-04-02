"""UserManager — multi-user Telegram identity and wallet auto-creation.

Manages the mapping between Telegram user IDs and their assigned custodial
wallet.  On first interaction the user is auto-created and a wallet is
provisioned transparently.

Schema::

    User:
        telegram_user_id  (primary key, int)
        wallet_id         (str)
        created_at        (float, unix timestamp)

Rules:
    - get_or_create_user is idempotent — safe to call on every request.
    - No private keys are stored or returned.
    - No withdraw functionality.

Usage::

    wm  = WalletManager()
    mgr = UserManager(wallet_manager=wm)

    user = await mgr.get_or_create_user(telegram_user_id=123456789)
    # user.wallet_id is ready to use
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from ...wallet.wallet_manager import WalletManager

log = structlog.get_logger()


@dataclass
class UserRecord:
    """Represents a registered bot user.

    Attributes:
        telegram_user_id: Telegram integer user ID (primary key).
        wallet_id: Assigned custodial wallet identifier.
        created_at: Unix timestamp of first interaction.
    """
    telegram_user_id: int
    wallet_id: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "telegram_user_id": self.telegram_user_id,
            "wallet_id": self.wallet_id,
            "created_at": self.created_at,
        }


class UserManager:
    """Manages Telegram user → wallet mapping with auto-provisioning.

    Args:
        wallet_manager: WalletManager instance for wallet creation.
    """

    def __init__(self, wallet_manager: WalletManager) -> None:
        self._wm = wallet_manager
        self._users: dict[int, UserRecord] = {}     # telegram_user_id → UserRecord
        self._lock = asyncio.Lock()

        log.info("user_manager_initialized")

    # ── Primary API ────────────────────────────────────────────────────────────

    async def get_or_create_user(self, telegram_user_id: int) -> UserRecord:
        """Return existing user or create a new one with auto-assigned wallet.

        Idempotent: calling multiple times with the same ID is safe.

        Args:
            telegram_user_id: Telegram user integer ID.

        Returns:
            UserRecord with wallet_id already assigned.
        """
        async with self._lock:
            existing = self._users.get(telegram_user_id)
            if existing is not None:
                log.debug("user_found", telegram_user_id=telegram_user_id, wallet_id=existing.wallet_id)
                return existing

        # Create wallet outside lock to avoid nesting with WalletManager's lock
        wallet_id = await self._wm.create_wallet(user_id=telegram_user_id)

        async with self._lock:
            # Re-check after re-acquiring lock (another coroutine may have raced)
            existing = self._users.get(telegram_user_id)
            if existing is not None:
                return existing

            record = UserRecord(
                telegram_user_id=telegram_user_id,
                wallet_id=wallet_id,
            )
            self._users[telegram_user_id] = record

            log.info(
                "user_created",
                telegram_user_id=telegram_user_id,
                wallet_id=wallet_id,
                created_at=record.created_at,
            )
            return record

    async def get_user_wallet(self, telegram_user_id: int) -> Optional[str]:
        """Return wallet_id for an existing user without creating one.

        Args:
            telegram_user_id: Telegram user integer ID.

        Returns:
            wallet_id string or None if user does not exist.
        """
        async with self._lock:
            record = self._users.get(telegram_user_id)
            if record is None:
                log.warning("user_not_found", telegram_user_id=telegram_user_id)
                return None
            return record.wallet_id

    def user_count(self) -> int:
        """Return total number of registered users."""
        return len(self._users)
