"""Phase 11.4 — UserManager: User identity + wallet assignment with SQLite persistence.

Key methods:
    get_or_create_user(user_id) → dict  (idempotent)
    wallet_id_for_user(user_id) → Optional[str]
    user_count                  → int
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional

import structlog

from .wallet_manager import WalletManager

log = structlog.get_logger(__name__)


class UserManager:
    """Maps user IDs to wallets with SQLite-backed persistence."""

    def __init__(self, wallet_manager: WalletManager, db=None) -> None:
        self._wallet_manager = wallet_manager
        self._db = db
        self._users: Dict[str, str] = {}   # user_id → wallet_id
        self._lock = asyncio.Lock()

    async def get_or_create_user(self, user_id: str) -> dict:
        """Return existing or create new user with wallet assignment.

        Idempotent: calling multiple times with same user_id always
        returns the same wallet_id.

        Args:
            user_id: Telegram user ID or any unique string.

        Returns:
            {"user_id": ..., "wallet_id": ..., "created": bool}
        """
        # Fast path: in-memory cache
        async with self._lock:
            if user_id in self._users:
                return {"user_id": user_id,
                        "wallet_id": self._users[user_id],
                        "created": False}

        # Check DB
        if self._db:
            row = await self._db.get_user(user_id)
            if row:
                wallet_id = row["wallet_id"]
                # Restore wallet from DB if not in memory
                if not self._wallet_manager.get_wallet(wallet_id):
                    await self._wallet_manager.load_from_db(wallet_id)
                async with self._lock:
                    self._users[user_id] = wallet_id
                log.info("user_loaded_from_db", user_id=user_id, wallet_id=wallet_id)
                return {"user_id": user_id, "wallet_id": wallet_id, "created": False}

        # Create new user + wallet
        wallet_id = await self._wallet_manager.create_wallet(user_id)
        async with self._lock:
            self._users[user_id] = wallet_id

        if self._db:
            await self._db.upsert_user(user_id=user_id, wallet_id=wallet_id)

        log.info("user_created", user_id=user_id, wallet_id=wallet_id)
        return {"user_id": user_id, "wallet_id": wallet_id, "created": True}

    def wallet_id_for_user(self, user_id: str) -> Optional[str]:
        return self._users.get(user_id)

    @property
    def user_count(self) -> int:
        return len(self._users)
