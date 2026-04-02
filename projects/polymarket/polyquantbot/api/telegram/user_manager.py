"""UserManager — multi-user Telegram identity and wallet auto-creation.

Manages the mapping between Telegram user IDs and their assigned custodial
wallet.  On first interaction the user is auto-created and a wallet is
provisioned transparently.  Users and wallets are persisted to SQLite so
state survives restarts.

Schema::

    User:
        telegram_user_id  (primary key, int)
        wallet_id         (str)
        created_at        (float, unix timestamp)

Rules:
    - get_or_create_user is idempotent — safe to call on every request.
    - No private keys are stored or returned.
    - No withdraw functionality.
    - When a DB client is provided, users are loaded from the DB on first
      access and created + persisted immediately on first interaction.

Usage::

    db  = SQLiteClient(path="data/polyquantbot.db")
    await db.connect()
    wm  = WalletManager(db=db)
    mgr = UserManager(wallet_manager=wm, db=db)

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
from ...infra.db.sqlite_client import SQLiteClient

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

    On first interaction with a new user a wallet is auto-created.  When a
    DB client is provided the mapping is persisted to SQLite immediately
    and loaded on subsequent interactions (survives restarts).

    Args:
        wallet_manager: WalletManager instance for wallet creation.
        db: Optional SQLiteClient for persistence.  When None, operates in
            in-memory mode only.
    """

    def __init__(
        self,
        wallet_manager: WalletManager,
        db: Optional[SQLiteClient] = None,
    ) -> None:
        self._wm = wallet_manager
        self._db = db
        self._users: dict[int, UserRecord] = {}     # telegram_user_id → UserRecord
        self._lock = asyncio.Lock()

        log.info("user_manager_initialized", persistent=db is not None)

    # ── Primary API ────────────────────────────────────────────────────────────

    async def get_or_create_user(self, telegram_user_id: int) -> UserRecord:
        """Return existing user or create a new one with auto-assigned wallet.

        Idempotent: calling multiple times with the same ID is safe.

        On each call the method first checks the in-memory cache, then
        the DB (if configured), before creating a brand new record.

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

        # Check DB before creating (restore persisted user across restarts)
        if self._db is not None:
            db_row = await self._db.get_user(telegram_user_id)
            if db_row is not None:
                wallet_id = db_row["wallet_id"]
                created_at = float(db_row.get("created_at", time.time()))
                # Restore wallet state into WalletManager
                await self._wm.load_from_db(wallet_id=wallet_id, user_id=telegram_user_id)
                record = UserRecord(
                    telegram_user_id=telegram_user_id,
                    wallet_id=wallet_id,
                    created_at=created_at,
                )
                async with self._lock:
                    # Double-check after re-acquiring lock
                    if telegram_user_id not in self._users:
                        self._users[telegram_user_id] = record
                    else:
                        record = self._users[telegram_user_id]
                log.info(
                    "user_loaded_from_db",
                    telegram_user_id=telegram_user_id,
                    wallet_id=wallet_id,
                )
                return record

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

        # Persist immediately outside lock
        if self._db is not None:
            await self._db.upsert_user(
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
