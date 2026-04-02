"""Infra — DatabaseClient: Async PostgreSQL persistence for trades and metrics.

Provides an async PostgreSQL client using asyncpg with three tables:

    trades              — immutable trade records (idempotent upsert on trade_id)
    strategy_metrics    — point-in-time strategy performance snapshots
    allocation_history  — capital allocation weight snapshots over time

Design:
    - All writes are non-blocking async (no blocking IO).
    - insert_trade() is idempotent: ON CONFLICT DO NOTHING on trade_id.
    - Schema is auto-created on connect (CREATE TABLE IF NOT EXISTS).
    - Fail-safe: DB failures are logged and swallowed — never crash trading.
    - Retry: up to 3 attempts with backoff on transient errors.
    - Structured logging on every operation.
    - Connection pool with min=2, max=10 connections.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_DSN = "postgresql://polyquantbot:polyquantbot@localhost:5432/polyquantbot"
_POOL_MIN: int = 2
_POOL_MAX: int = 10
_OP_TIMEOUT_S: float = 5.0
_MAX_RETRIES: int = 3
_RETRY_BASE_S: float = 0.5

# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id        TEXT        PRIMARY KEY,
    strategy_id     TEXT        NOT NULL,
    market_id       TEXT        NOT NULL,
    side            TEXT        NOT NULL,
    size_usd        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    price           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    expected_ev     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    pnl             DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    won             BOOLEAN     NOT NULL DEFAULT FALSE,
    mode            TEXT        NOT NULL DEFAULT 'PAPER',
    executed_at     DOUBLE PRECISION NOT NULL,
    inserted_at     DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    metadata        JSONB
);
"""

_DDL_STRATEGY_METRICS = """
CREATE TABLE IF NOT EXISTS strategy_metrics (
    id              BIGSERIAL   PRIMARY KEY,
    strategy_id     TEXT        NOT NULL,
    signals_generated  INTEGER  NOT NULL DEFAULT 0,
    trades_executed    INTEGER  NOT NULL DEFAULT 0,
    wins            INTEGER     NOT NULL DEFAULT 0,
    losses          INTEGER     NOT NULL DEFAULT 0,
    total_ev_captured  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    total_pnl       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    win_rate        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    ev_capture_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    recorded_at     DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);
"""

_DDL_ALLOCATION_HISTORY = """
CREATE TABLE IF NOT EXISTS allocation_history (
    id              BIGSERIAL   PRIMARY KEY,
    strategy_weights  JSONB     NOT NULL,
    position_sizes    JSONB     NOT NULL,
    disabled_strategies  JSONB  NOT NULL DEFAULT '[]',
    suppressed_strategies JSONB NOT NULL DEFAULT '[]',
    total_allocated_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    bankroll        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    mode            TEXT        NOT NULL DEFAULT 'PAPER',
    recorded_at     DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);
"""


# ── DatabaseClient ─────────────────────────────────────────────────────────────


class DatabaseClient:
    """Async PostgreSQL client for PolyQuantBot persistence.

    Uses asyncpg connection pool.  Schema is created automatically on
    first :meth:`connect` call.

    Args:
        dsn: PostgreSQL DSN (default: env DB_DSN or localhost default).
        pool_min: Minimum pool connections.
        pool_max: Maximum pool connections.
        op_timeout_s: Timeout per DB operation in seconds.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool_min: int = _POOL_MIN,
        pool_max: int = _POOL_MAX,
        op_timeout_s: float = _OP_TIMEOUT_S,
    ) -> None:
        self._dsn = dsn or os.environ.get("DB_DSN", _DEFAULT_DSN)
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._op_timeout_s = op_timeout_s
        self._pool: Optional[Any] = None  # asyncpg.Pool
        self._lock = asyncio.Lock()

        log.info(
            "db_client_initialized",
            dsn=self._dsn[:32] + "..." if len(self._dsn) > 32 else self._dsn,
            pool_min=pool_min,
            pool_max=pool_max,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create connection pool and apply DDL.  Idempotent."""
        async with self._lock:
            if self._pool is not None:
                return
            try:
                import asyncpg  # type: ignore[import]
                self._pool = await asyncio.wait_for(
                    asyncpg.create_pool(
                        dsn=self._dsn,
                        min_size=self._pool_min,
                        max_size=self._pool_max,
                    ),
                    timeout=10.0,
                )
                await self._apply_schema()
                log.info("db_client_connected_and_schema_applied")
            except Exception as exc:
                self._pool = None
                log.error(
                    "db_client_connect_failed",
                    error=str(exc),
                )

    async def close(self) -> None:
        """Close the connection pool gracefully."""
        if self._pool is not None:
            try:
                await self._pool.close()
                log.info("db_client_closed")
            except Exception as exc:
                log.warning("db_client_close_error", error=str(exc))
            finally:
                self._pool = None

    async def _apply_schema(self) -> None:
        """Create tables if they do not exist yet."""
        async with self._pool.acquire() as conn:
            await conn.execute(_DDL_TRADES)
            await conn.execute(_DDL_STRATEGY_METRICS)
            await conn.execute(_DDL_ALLOCATION_HISTORY)
        log.info("db_schema_applied")

    # ── Trades ────────────────────────────────────────────────────────────────

    async def insert_trade(self, trade: Dict[str, Any]) -> bool:
        """Insert a trade record.  Idempotent: ON CONFLICT DO NOTHING.

        Expected keys in *trade*:
            trade_id, strategy_id, market_id, side, size_usd, price,
            expected_ev, pnl, won, mode, executed_at.
            Optional: metadata (dict).

        Args:
            trade: Trade data dict.

        Returns:
            True on insert or duplicate-skip, False on error.
        """
        sql = """
            INSERT INTO trades (
                trade_id, strategy_id, market_id, side,
                size_usd, price, expected_ev, pnl, won, mode,
                executed_at, inserted_at, metadata
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8, $9, $10,
                $11, $12, $13
            )
            ON CONFLICT (trade_id) DO NOTHING
        """
        args = (
            str(trade.get("trade_id", "")),
            str(trade.get("strategy_id", "")),
            str(trade.get("market_id", "")),
            str(trade.get("side", "")),
            float(trade.get("size_usd", 0.0)),
            float(trade.get("price", 0.0)),
            float(trade.get("expected_ev", 0.0)),
            float(trade.get("pnl", 0.0)),
            bool(trade.get("won", False)),
            str(trade.get("mode", "PAPER")),
            float(trade.get("executed_at", time.time())),
            time.time(),
            json.dumps(trade.get("metadata")) if trade.get("metadata") else None,
        )
        return await self._execute(sql, *args, op_label="insert_trade")

    async def get_recent_trades(
        self, limit: int = 100, strategy_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch recent trade records.

        Args:
            limit: Maximum number of records to return.
            strategy_id: Optional filter by strategy.

        Returns:
            List of trade dicts ordered by executed_at DESC.
        """
        if strategy_id:
            sql = """
                SELECT * FROM trades
                WHERE strategy_id = $1
                ORDER BY executed_at DESC LIMIT $2
            """
            return await self._fetch(sql, strategy_id, limit, op_label="get_recent_trades_filtered")
        sql = "SELECT * FROM trades ORDER BY executed_at DESC LIMIT $1"
        return await self._fetch(sql, limit, op_label="get_recent_trades")

    # ── Strategy metrics ──────────────────────────────────────────────────────

    async def insert_strategy_metrics(
        self, strategy_id: str, metrics: Dict[str, Any]
    ) -> bool:
        """Append a point-in-time metrics snapshot for a strategy.

        Args:
            strategy_id: Strategy name.
            metrics: Metrics dict from StrategyMetrics.to_dict().

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO strategy_metrics (
                strategy_id, signals_generated, trades_executed,
                wins, losses, total_ev_captured, total_pnl,
                win_rate, ev_capture_rate, recorded_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """
        args = (
            strategy_id,
            int(metrics.get("signals_generated", 0)),
            int(metrics.get("trades_executed", 0)),
            int(metrics.get("wins", 0)),
            int(metrics.get("losses", 0)),
            float(metrics.get("total_ev_captured", 0.0)),
            float(metrics.get("total_pnl", 0.0)),
            float(metrics.get("win_rate", 0.0)),
            float(metrics.get("ev_capture_rate", 0.0)),
            time.time(),
        )
        return await self._execute(sql, *args, op_label="insert_strategy_metrics")

    # ── Allocation history ────────────────────────────────────────────────────

    async def insert_allocation_history(
        self, allocation: Dict[str, Any]
    ) -> bool:
        """Append an allocation snapshot record.

        Expected keys: strategy_weights, position_sizes, disabled_strategies,
            suppressed_strategies, total_allocated_usd, bankroll, mode.

        Args:
            allocation: AllocationSnapshot data dict.

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO allocation_history (
                strategy_weights, position_sizes, disabled_strategies,
                suppressed_strategies, total_allocated_usd, bankroll,
                mode, recorded_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        args = (
            json.dumps(allocation.get("strategy_weights", {})),
            json.dumps(allocation.get("position_sizes", {})),
            json.dumps(allocation.get("disabled_strategies", [])),
            json.dumps(allocation.get("suppressed_strategies", [])),
            float(allocation.get("total_allocated_usd", 0.0)),
            float(allocation.get("bankroll", 0.0)),
            str(allocation.get("mode", "PAPER")),
            time.time(),
        )
        return await self._execute(sql, *args, op_label="insert_allocation_history")

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _execute(self, sql: str, *args: Any, op_label: str = "execute") -> bool:
        """Execute a write query with retry.

        Returns:
            True on success, False on failure.
        """
        if self._pool is None:
            await self.connect()
        if self._pool is None:
            log.warning("db_execute_skipped_no_pool", op=op_label)
            return False

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._pool.acquire() as conn:
                    await asyncio.wait_for(
                        conn.execute(sql, *args),
                        timeout=self._op_timeout_s,
                    )
                log.debug("db_execute_ok", op=op_label, attempt=attempt)
                return True
            except asyncio.TimeoutError:
                log.warning("db_execute_timeout", op=op_label, attempt=attempt)
            except Exception as exc:
                log.warning(
                    "db_execute_error",
                    op=op_label,
                    attempt=attempt,
                    error=str(exc),
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))

        log.error("db_execute_all_attempts_failed", op=op_label)
        return False

    async def _fetch(
        self, sql: str, *args: Any, op_label: str = "fetch"
    ) -> List[Dict[str, Any]]:
        """Execute a read query and return list of row dicts.

        Returns:
            List of dicts, empty on failure.
        """
        if self._pool is None:
            await self.connect()
        if self._pool is None:
            log.warning("db_fetch_skipped_no_pool", op=op_label)
            return []

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._pool.acquire() as conn:
                    rows = await asyncio.wait_for(
                        conn.fetch(sql, *args),
                        timeout=self._op_timeout_s,
                    )
                log.debug("db_fetch_ok", op=op_label, rows=len(rows), attempt=attempt)
                return [dict(row) for row in rows]
            except asyncio.TimeoutError:
                log.warning("db_fetch_timeout", op=op_label, attempt=attempt)
            except Exception as exc:
                log.warning(
                    "db_fetch_error",
                    op=op_label,
                    attempt=attempt,
                    error=str(exc),
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))

        log.error("db_fetch_all_attempts_failed", op=op_label)
        return []

    async def ping(self) -> bool:
        """Check DB connectivity.

        Returns:
            True if pool can execute SELECT 1, False otherwise.
        """
        if self._pool is None:
            await self.connect()
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await asyncio.wait_for(
                    conn.fetchval("SELECT 1"),
                    timeout=self._op_timeout_s,
                )
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        connected = self._pool is not None
        return f"<DatabaseClient dsn=...{self._dsn[-20:]} connected={connected}>"
