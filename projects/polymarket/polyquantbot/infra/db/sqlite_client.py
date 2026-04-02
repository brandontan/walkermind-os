"""infra/db/sqlite_client.py — Async SQLite persistence for users, wallets, and trades.

Provides an async-safe SQLite client backed by aiosqlite.  All operations
are idempotent and safe to call on every request.

Tables:

    users:
        telegram_user_id  INTEGER  PRIMARY KEY
        wallet_id         TEXT     NOT NULL
        created_at        REAL     NOT NULL

    wallets:
        wallet_id         TEXT     PRIMARY KEY
        balance           REAL     NOT NULL DEFAULT 0.0
        exposure          REAL     NOT NULL DEFAULT 0.0
        updated_at        REAL     NOT NULL

    trades:
        trade_id          TEXT     PRIMARY KEY
        user_id           INTEGER  NOT NULL
        size              REAL     NOT NULL DEFAULT 0.0
        fee               REAL     NOT NULL DEFAULT 0.0
        pnl_net           REAL     NOT NULL DEFAULT 0.0
        timestamp         REAL     NOT NULL

Design:
    - Auto-creates schema on first :meth:`connect` call (safe for first run).
    - All writes use transactions with retry on transient lock errors.
    - Fail-safe: DB errors are logged; never crash trading logic.
    - asyncio single event-loop only.
    - Zero silent failure: every error is logged before returning default.

Usage::

    db = SQLiteClient(path="data/polyquantbot.db")
    await db.connect()

    await db.upsert_user(telegram_user_id=123, wallet_id="wlt_abc")
    await db.upsert_wallet(wallet_id="wlt_abc", balance=0.0, exposure=0.0)
    user = await db.get_user(telegram_user_id=123)
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import structlog

if TYPE_CHECKING:
    import aiosqlite as _aiosqlite

log = structlog.get_logger()

_DEFAULT_DB_PATH: str = "data/polyquantbot.db"
_MAX_RETRIES: int = 3
_RETRY_BASE_S: float = 0.1

# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    telegram_user_id  INTEGER  PRIMARY KEY,
    wallet_id         TEXT     NOT NULL,
    created_at        REAL     NOT NULL
);
"""

_DDL_WALLETS = """
CREATE TABLE IF NOT EXISTS wallets (
    wallet_id   TEXT  PRIMARY KEY,
    balance     REAL  NOT NULL DEFAULT 0.0,
    exposure    REAL  NOT NULL DEFAULT 0.0,
    updated_at  REAL  NOT NULL
);
"""

_DDL_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id   TEXT     PRIMARY KEY,
    user_id    INTEGER  NOT NULL,
    size       REAL     NOT NULL DEFAULT 0.0,
    fee        REAL     NOT NULL DEFAULT 0.0,
    pnl_net    REAL     NOT NULL DEFAULT 0.0,
    timestamp  REAL     NOT NULL
);
"""


# ── SQLiteClient ──────────────────────────────────────────────────────────────


class SQLiteClient:
    """Async SQLite persistence client for PolyQuantBot.

    Uses aiosqlite for non-blocking I/O.  Schema is auto-created on
    first :meth:`connect` call — safe for a fresh first run.

    Args:
        path: Filesystem path to the SQLite database file.
              Parent directory is created automatically if missing.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path: str = path or os.environ.get("SQLITE_DB_PATH", _DEFAULT_DB_PATH)
        self._db: Optional["_aiosqlite.Connection"] = None
        self._lock = asyncio.Lock()

        log.info("sqlite_client_initialized", path=self._path)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open the database connection and apply DDL.  Idempotent."""
        async with self._lock:
            if self._db is not None:
                return
            try:
                import aiosqlite  # type: ignore[import]

                # Ensure parent directory exists
                parent = os.path.dirname(self._path)
                if parent:
                    os.makedirs(parent, exist_ok=True)

                self._db = await aiosqlite.connect(self._path)
                self._db.row_factory = aiosqlite.Row
                await self._apply_schema()
                log.info("sqlite_client_connected", path=self._path)
            except Exception as exc:
                self._db = None
                log.error("sqlite_client_connect_failed", error=str(exc))

    async def close(self) -> None:
        """Close the database connection gracefully."""
        async with self._lock:
            if self._db is not None:
                try:
                    await self._db.close()
                    log.info("sqlite_client_closed")
                except Exception as exc:
                    log.warning("sqlite_client_close_error", error=str(exc))
                finally:
                    self._db = None

    async def _apply_schema(self) -> None:
        """Create tables if they do not exist yet."""
        assert self._db is not None
        await self._db.execute(_DDL_USERS)
        await self._db.execute(_DDL_WALLETS)
        await self._db.execute(_DDL_TRADES)
        await self._db.commit()
        log.info("sqlite_schema_applied")

    # ── Users ─────────────────────────────────────────────────────────────────

    async def upsert_user(
        self,
        telegram_user_id: int,
        wallet_id: str,
        created_at: Optional[float] = None,
    ) -> bool:
        """Insert or update a user record.  Idempotent.

        Args:
            telegram_user_id: Telegram integer user ID.
            wallet_id: Assigned custodial wallet identifier.
            created_at: Optional creation timestamp (defaults to now).

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO users (telegram_user_id, wallet_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET wallet_id=excluded.wallet_id
        """
        return await self._execute(
            sql,
            telegram_user_id,
            wallet_id,
            created_at or time.time(),
            op_label="upsert_user",
        )

    async def get_user(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a user record by Telegram user ID.

        Args:
            telegram_user_id: Telegram integer user ID.

        Returns:
            Dict with telegram_user_id, wallet_id, created_at — or None if not found.
        """
        sql = "SELECT telegram_user_id, wallet_id, created_at FROM users WHERE telegram_user_id = ?"
        rows = await self._fetch(sql, telegram_user_id, op_label="get_user")
        if rows:
            return dict(rows[0])
        return None

    # ── Wallets ───────────────────────────────────────────────────────────────

    async def upsert_wallet(
        self,
        wallet_id: str,
        balance: float,
        exposure: float,
        updated_at: Optional[float] = None,
    ) -> bool:
        """Insert or update a wallet record.  Idempotent.

        Args:
            wallet_id: Wallet identifier.
            balance: Current net balance (USD).
            exposure: Current open exposure (USD).
            updated_at: Optional update timestamp (defaults to now).

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO wallets (wallet_id, balance, exposure, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(wallet_id) DO UPDATE SET
                balance=excluded.balance,
                exposure=excluded.exposure,
                updated_at=excluded.updated_at
        """
        return await self._execute(
            sql,
            wallet_id,
            balance,
            exposure,
            updated_at or time.time(),
            op_label="upsert_wallet",
        )

    async def get_wallet(self, wallet_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a wallet record by wallet ID.

        Args:
            wallet_id: Wallet identifier.

        Returns:
            Dict with wallet_id, balance, exposure, updated_at — or None if not found.
        """
        sql = "SELECT wallet_id, balance, exposure, updated_at FROM wallets WHERE wallet_id = ?"
        rows = await self._fetch(sql, wallet_id, op_label="get_wallet")
        if rows:
            return dict(rows[0])
        return None

    # ── Trades ────────────────────────────────────────────────────────────────

    async def insert_trade(
        self,
        user_id: int,
        size: float,
        fee: float,
        pnl_net: float,
        trade_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> bool:
        """Insert a trade record.  Idempotent: ON CONFLICT DO NOTHING.

        Args:
            user_id: Telegram user ID (foreign key).
            size: Trade size in USD.
            fee: Fee charged (= size * fee_rate).
            pnl_net: Net PnL after fee.
            trade_id: Optional unique trade identifier (auto-generated if None).
            timestamp: Optional trade timestamp (defaults to now).

        Returns:
            True on insert or duplicate-skip, False on error.
        """
        sql = """
            INSERT INTO trades (trade_id, user_id, size, fee, pnl_net, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO NOTHING
        """
        return await self._execute(
            sql,
            trade_id or f"trd_{uuid.uuid4().hex[:16]}",
            user_id,
            size,
            fee,
            pnl_net,
            timestamp or time.time(),
            op_label="insert_trade",
        )

    # ── Health ────────────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Check DB connectivity.

        Returns:
            True if the connection is open and responsive.
        """
        if self._db is None:
            await self.connect()
        if self._db is None:
            return False
        try:
            async with self._db.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except Exception:
            return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _execute(self, sql: str, *args: Any, op_label: str = "execute") -> bool:
        """Execute a write statement inside a transaction with retry.

        Returns:
            True on success, False on failure.
        """
        if self._db is None:
            await self.connect()
        if self._db is None:
            log.warning("sqlite_execute_skipped_no_conn", op=op_label)
            return False

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                await self._db.execute(sql, args)
                await self._db.commit()
                log.debug("sqlite_execute_ok", op=op_label, attempt=attempt)
                return True
            except Exception as exc:
                log.warning(
                    "sqlite_execute_error",
                    op=op_label,
                    attempt=attempt,
                    error=str(exc),
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))

        log.error("sqlite_execute_all_attempts_failed", op=op_label)
        return False

    async def _fetch(
        self, sql: str, *args: Any, op_label: str = "fetch"
    ) -> list:
        """Execute a read query and return a list of rows.

        Returns:
            List of aiosqlite.Row objects, empty on failure.
        """
        if self._db is None:
            await self.connect()
        if self._db is None:
            log.warning("sqlite_fetch_skipped_no_conn", op=op_label)
            return []

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._db.execute(sql, args) as cursor:
                    rows = await cursor.fetchall()
                log.debug("sqlite_fetch_ok", op=op_label, rows=len(rows), attempt=attempt)
                return rows
            except Exception as exc:
                log.warning(
                    "sqlite_fetch_error",
                    op=op_label,
                    attempt=attempt,
                    error=str(exc),
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))

        log.error("sqlite_fetch_all_attempts_failed", op=op_label)
        return []

    def __repr__(self) -> str:
        connected = self._db is not None
        return f"<SQLiteClient path={self._path!r} connected={connected}>"
