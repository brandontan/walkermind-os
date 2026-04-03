"""core/wallet/repository.py — WalletRepository: PostgreSQL-backed wallet storage.

Persists wallets to the ``wallets`` table via DatabaseClient (asyncpg).

Table schema (created automatically via :meth:`ensure_schema`):

    wallets (user_id PK, address, encrypted_private_key, created_at, updated_at)

Rules:
    - ``encrypted_private_key`` is NEVER logged.
    - :meth:`get_wallet` returns ``None`` (not an error) when record is absent.
    - :meth:`create_wallet` is idempotent: ``ON CONFLICT DO NOTHING`` on ``user_id``.
      After insert it re-reads the row so a pre-existing record is always returned.
    - :meth:`update_wallet` updates the ``address`` and ``updated_at`` columns.
    - All DB errors are propagated to the caller for explicit handling.
"""
from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

import structlog

from .models import WalletModel

if TYPE_CHECKING:
    from ...infra.db import DatabaseClient

log = structlog.get_logger(__name__)

# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL_WALLETS = """
CREATE TABLE IF NOT EXISTS wallets (
    user_id                 BIGINT           PRIMARY KEY,
    address                 TEXT             NOT NULL,
    encrypted_private_key   TEXT             NOT NULL,
    created_at              DOUBLE PRECISION NOT NULL,
    updated_at              DOUBLE PRECISION NOT NULL
);
"""

# ── SQL statements ────────────────────────────────────────────────────────────

_SQL_GET = (
    "SELECT user_id, address, encrypted_private_key, created_at "
    "FROM wallets WHERE user_id = $1"
)

_SQL_INSERT = """
    INSERT INTO wallets (user_id, address, encrypted_private_key, created_at, updated_at)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (user_id) DO NOTHING
"""

_SQL_UPDATE = (
    "UPDATE wallets SET address = $2, updated_at = $3 WHERE user_id = $1"
)


# ── WalletRepository ──────────────────────────────────────────────────────────


class WalletRepository:
    """PostgreSQL-backed wallet persistence layer.

    Wraps :class:`~infra.db.DatabaseClient` with wallet-domain types.

    Args:
        db: A connected :class:`~infra.db.DatabaseClient` instance.
    """

    def __init__(self, db: "DatabaseClient") -> None:
        self._db = db

    async def ensure_schema(self) -> None:
        """Create the ``wallets`` table if it does not exist.

        Idempotent — safe to call on every startup.
        """
        await self._db._execute(_DDL_WALLETS, op_label="wallet_ensure_schema")
        log.info("wallet_schema_ensured")

    async def get_wallet(self, user_id: int) -> Optional[WalletModel]:
        """Fetch wallet by *user_id*.

        Args:
            user_id: Telegram (or other) user integer ID.

        Returns:
            :class:`WalletModel` when found, ``None`` otherwise.
        """
        rows = await self._db._fetch(_SQL_GET, user_id, op_label="wallet_get")
        if not rows:
            return None
        row = rows[0]
        return WalletModel(
            user_id=int(row["user_id"]),
            address=str(row["address"]),
            encrypted_private_key=str(row["encrypted_private_key"]),
            created_at=float(row["created_at"]),
        )

    async def create_wallet(self, user_id: int, wallet: WalletModel) -> WalletModel:
        """Persist a new wallet record (idempotent).

        Uses ``ON CONFLICT DO NOTHING`` so a concurrent insert for the same
        ``user_id`` will not overwrite the winner.  Always returns the record
        that is stored in the DB (pre-existing or newly inserted).

        Args:
            user_id: Telegram user ID (must equal ``wallet.user_id``).
            wallet: The wallet to persist.

        Returns:
            The :class:`WalletModel` that is authoritative in the DB.
        """
        now = time.time()
        await self._db._execute(
            _SQL_INSERT,
            int(wallet.user_id),
            str(wallet.address),
            str(wallet.encrypted_private_key),
            float(wallet.created_at),
            now,
            op_label="wallet_create",
        )
        existing = await self.get_wallet(user_id)
        log.info(
            "wallet_persisted",
            user_id=user_id,
            address=existing.address if existing else wallet.address,
        )
        return existing if existing is not None else wallet

    async def update_wallet(self, wallet: WalletModel) -> None:
        """Update the ``address`` (and ``updated_at``) for an existing wallet.

        Args:
            wallet: Wallet record with the new address.
        """
        now = time.time()
        await self._db._execute(
            _SQL_UPDATE,
            int(wallet.user_id),
            str(wallet.address),
            now,
            op_label="wallet_update",
        )
        log.info("wallet_address_updated", user_id=wallet.user_id, address=wallet.address)
