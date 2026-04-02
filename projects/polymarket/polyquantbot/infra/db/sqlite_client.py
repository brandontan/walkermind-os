"""Phase 11.4 — SQLiteClient: Async SQLite persistence for users, wallets, trades.

Schema:
    users   — user_id → wallet_id mapping
    wallets — balance, exposure, total_trades per wallet
    trades  — immutable trade records

Design:
    - All writes idempotent (ON CONFLICT DO NOTHING / DO UPDATE)
    - 3 retries with exponential backoff on transient errors
    - WAL mode for concurrent read performance
    - Fail-safe: errors logged and returned, never crash trading
    - Auto-creates DB file and tables on first connect
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
import structlog

log = structlog.get_logger(__name__)

_DEFAULT_DB_PATH = os.environ.get("SQLITE_DB_PATH", "data/polyquantbot.db")
_MAX_RETRIES = 3
_RETRY_BASE_S = 0.2

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY NOT NULL,
    wallet_id  TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS wallets (
    wallet_id    TEXT PRIMARY KEY NOT NULL,
    balance      REAL NOT NULL DEFAULT 0.0,
    exposure     REAL NOT NULL DEFAULT 0.0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    updated_at   REAL NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id   TEXT PRIMARY KEY NOT NULL,
    wallet_id  TEXT NOT NULL,
    market_id  TEXT,
    side       TEXT,
    size       REAL,
    price      REAL,
    pnl_net    REAL,
    fee        REAL,
    timestamp  REAL NOT NULL DEFAULT (unixepoch())
);
"""


class SQLiteClient:
    """Async SQLite client for PolyQuantBot persistence."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_DDL)
        await self._conn.commit()
        log.info("sqlite_client_connected", db_path=self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def is_connected(self) -> bool:
        if not self._conn:
            return False
        try:
            await self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    # ── Retry helper ──────────────────────────────────────────────────────────

    async def _execute(self, sql: str, params: tuple = ()) -> Optional[Any]:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._conn.execute(sql, params) as cur:
                    await self._conn.commit()
                    return cur
            except Exception as exc:
                log.warning("sqlite_execute_error", attempt=attempt, sql=sql[:60], error=str(exc))
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))
                else:
                    log.error("sqlite_execute_failed", sql=sql[:60], error=str(exc))
                    return None

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._conn.execute(sql, params) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None
            except Exception as exc:
                log.warning("sqlite_fetchone_error", attempt=attempt, error=str(exc))
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))
        return None

    async def _fetchall(self, sql: str, params: tuple = ()) -> List[Dict]:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._conn.execute(sql, params) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]
            except Exception as exc:
                log.warning("sqlite_fetchall_error", attempt=attempt, error=str(exc))
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))
        return []

    # ── Users ─────────────────────────────────────────────────────────────────

    async def upsert_user(self, user_id: str, wallet_id: str) -> bool:
        res = await self._execute(
            "INSERT INTO users (user_id, wallet_id, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id, wallet_id, time.time()),
        )
        log.info("sqlite_upsert_user", user_id=user_id, wallet_id=wallet_id)
        return res is not None

    async def get_user(self, user_id: str) -> Optional[Dict]:
        return await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    async def get_user_count(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) as cnt FROM users")
        return row["cnt"] if row else 0

    # ── Wallets ───────────────────────────────────────────────────────────────

    async def upsert_wallet(self, wallet_id: str, balance: float,
                            exposure: float, total_trades: int) -> bool:
        res = await self._execute(
            "INSERT INTO wallets (wallet_id, balance, exposure, total_trades, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(wallet_id) DO UPDATE SET "
            "balance=excluded.balance, exposure=excluded.exposure, "
            "total_trades=excluded.total_trades, updated_at=excluded.updated_at",
            (wallet_id, balance, exposure, total_trades, time.time()),
        )
        log.info("sqlite_upsert_wallet", wallet_id=wallet_id, balance=balance)
        return res is not None

    async def get_wallet(self, wallet_id: str) -> Optional[Dict]:
        return await self._fetchone("SELECT * FROM wallets WHERE wallet_id = ?", (wallet_id,))

    # ── Trades ────────────────────────────────────────────────────────────────

    async def insert_trade(self, trade_id: str, wallet_id: str, market_id: str,
                           side: str, size: float, price: float,
                           pnl_net: float, fee: float) -> bool:
        res = await self._execute(
            "INSERT INTO trades (trade_id, wallet_id, market_id, side, size, price, "
            "pnl_net, fee, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(trade_id) DO NOTHING",
            (trade_id, wallet_id, market_id, side, size, price, pnl_net, fee, time.time()),
        )
        log.info("sqlite_insert_trade", trade_id=trade_id, wallet_id=wallet_id,
                 pnl_net=pnl_net, fee=fee)
        return res is not None

    async def get_trades(self, wallet_id: str, limit: int = 50) -> List[Dict]:
        return await self._fetchall(
            "SELECT * FROM trades WHERE wallet_id = ? ORDER BY timestamp DESC LIMIT ?",
            (wallet_id, limit),
        )
