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
    user_id         TEXT        NOT NULL DEFAULT '',
    strategy_id     TEXT        NOT NULL,
    market_id       TEXT        NOT NULL,
    side            TEXT        NOT NULL,
    size_usd        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    price           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    entry_price     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    expected_ev     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    pnl             DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    won             BOOLEAN     NOT NULL DEFAULT FALSE,
    status          TEXT        NOT NULL DEFAULT 'open',
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

_DDL_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    user_id         TEXT        NOT NULL DEFAULT '',
    market_id       TEXT        NOT NULL,
    avg_price       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    size            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    updated_at      DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    PRIMARY KEY (user_id, market_id)
);
"""

_DDL_STRATEGY_STATE = """
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy    TEXT        PRIMARY KEY,
    active      BOOLEAN     NOT NULL DEFAULT TRUE,
    updated_at  DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);
"""

_DDL_MIGRATE_TRADES_USER_ID = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trades' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE trades ADD COLUMN user_id TEXT NOT NULL DEFAULT '';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trades' AND column_name = 'status'
    ) THEN
        ALTER TABLE trades ADD COLUMN status TEXT NOT NULL DEFAULT 'open';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trades' AND column_name = 'entry_price'
    ) THEN
        ALTER TABLE trades ADD COLUMN entry_price DOUBLE PRECISION NOT NULL DEFAULT 0.0;
    END IF;
END
$$;
"""

# ── Pre-capital hardening: wallet / positions / ledger persistence ─────────────

_DDL_WALLET_STATE = """
CREATE TABLE IF NOT EXISTS wallet_state (
    id          BIGSERIAL   PRIMARY KEY,
    cash        DOUBLE PRECISION NOT NULL,
    locked      DOUBLE PRECISION NOT NULL,
    equity      DOUBLE PRECISION NOT NULL,
    snapshot_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);
"""

_DDL_PAPER_POSITIONS = """
CREATE TABLE IF NOT EXISTS paper_positions (
    market_id       TEXT        PRIMARY KEY,
    side            TEXT        NOT NULL,
    size            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    entry_price     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    current_price   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    unrealized_pnl  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status          TEXT        NOT NULL DEFAULT 'OPEN',
    opened_at       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    closed_at       DOUBLE PRECISION,
    trade_ids       JSONB       NOT NULL DEFAULT '[]',
    updated_at      DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);
"""

_DDL_TRADE_LEDGER = """
CREATE TABLE IF NOT EXISTS trade_ledger (
    trade_id        TEXT        PRIMARY KEY,
    market_id       TEXT        NOT NULL,
    action          TEXT        NOT NULL,
    price           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    size            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    fee             DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    realized_pnl    DOUBLE PRECISION,
    ledger_ts       TEXT        NOT NULL DEFAULT '',
    inserted_at     DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
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
        """Create connection pool and apply DDL.  Idempotent.

        Raises:
            RuntimeError: If the connection pool cannot be created.
        """
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
                raise RuntimeError(f"Database unavailable — cannot connect: {exc}") from exc

    async def ensure_schema(self) -> None:
        """Ensure all tables exist.  Raises if pool is not connected."""
        if self._pool is None:
            raise RuntimeError("Database not connected — call connect() first")
        await self._apply_schema()
        log.info("db_ensure_schema_ok")

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
        """Create tables if they do not exist yet, and run migrations."""
        async with self._pool.acquire() as conn:
            await conn.execute(_DDL_TRADES)
            await conn.execute(_DDL_STRATEGY_METRICS)
            await conn.execute(_DDL_ALLOCATION_HISTORY)
            await conn.execute(_DDL_POSITIONS)
            await conn.execute(_DDL_STRATEGY_STATE)
            await conn.execute(_DDL_MIGRATE_TRADES_USER_ID)
            # Pre-capital hardening tables
            await conn.execute(_DDL_WALLET_STATE)
            await conn.execute(_DDL_PAPER_POSITIONS)
            await conn.execute(_DDL_TRADE_LEDGER)
        log.info("db_schema_applied")

    # ── Trades ────────────────────────────────────────────────────────────────

    async def insert_trade(self, trade: Dict[str, Any]) -> bool:
        """Insert a trade record.  Idempotent: ON CONFLICT DO NOTHING.

        Expected keys in *trade*:
            trade_id, user_id, strategy_id, market_id, side, size_usd,
            price, entry_price, expected_ev, pnl, won, status, mode, executed_at.
            Optional: metadata (dict).

        Args:
            trade: Trade data dict.

        Returns:
            True on insert or duplicate-skip, False on error.
        """
        # entry_price defaults to price for backward compatibility
        entry_price = float(
            trade.get("entry_price", trade.get("price", 0.0))
        )
        sql = """
            INSERT INTO trades (
                trade_id, user_id, strategy_id, market_id, side,
                size_usd, price, entry_price, expected_ev, pnl,
                won, status, mode, executed_at, inserted_at, metadata
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16
            )
            ON CONFLICT (trade_id) DO NOTHING
        """
        args = (
            str(trade.get("trade_id", "")),
            str(trade.get("user_id", "")),
            str(trade.get("strategy_id", "")),
            str(trade.get("market_id", "")),
            str(trade.get("side", "")),
            float(trade.get("size_usd", 0.0)),
            float(trade.get("price", 0.0)),
            entry_price,
            float(trade.get("expected_ev", 0.0)),
            float(trade.get("pnl", 0.0)),
            bool(trade.get("won", False)),
            str(trade.get("status", "open")),
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

    async def update_trade_status(
        self, trade_id: str, status: str, pnl: Optional[float] = None, won: Optional[bool] = None
    ) -> bool:
        """Update the status (and optionally PnL/won) of an existing trade.

        Args:
            trade_id: Trade primary key.
            status: New status string (e.g. ``"closed"``, ``"settled"``).
            pnl: Realised PnL to record (optional).
            won: Whether the trade was profitable (optional).

        Returns:
            True on success, False on error.
        """
        if pnl is not None and won is not None:
            sql = """
                UPDATE trades SET status = $2, pnl = $3, won = $4
                WHERE trade_id = $1
            """
            return await self._execute(
                sql, trade_id, status, float(pnl), bool(won),
                op_label="update_trade_status_pnl",
            )
        if pnl is not None:
            sql = "UPDATE trades SET status = $2, pnl = $3 WHERE trade_id = $1"
            return await self._execute(
                sql, trade_id, status, float(pnl),
                op_label="update_trade_status_pnl",
            )
        sql = "UPDATE trades SET status = $2 WHERE trade_id = $1"
        return await self._execute(sql, trade_id, status, op_label="update_trade_status")

    # ── Positions ─────────────────────────────────────────────────────────────

    async def upsert_position(self, position: Dict[str, Any]) -> bool:
        """Insert or update a position record.

        Expected keys:
            user_id, market_id, avg_price, size.

        When a position with the same ``(user_id, market_id)`` already exists,
        the avg_price and size are overwritten.

        Args:
            position: Position data dict.

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO positions (user_id, market_id, avg_price, size, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, market_id) DO UPDATE
                SET avg_price  = EXCLUDED.avg_price,
                    size       = EXCLUDED.size,
                    updated_at = EXCLUDED.updated_at
        """
        args = (
            str(position.get("user_id", "")),
            str(position.get("market_id", "")),
            float(position.get("avg_price", 0.0)),
            float(position.get("size", 0.0)),
            time.time(),
        )
        return await self._execute(sql, *args, op_label="upsert_position")

    async def get_positions(
        self, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch open positions.

        Args:
            user_id: If given, returns only positions for this user.

        Returns:
            List of position dicts ordered by updated_at DESC.
        """
        if user_id:
            sql = """
                SELECT * FROM positions
                WHERE user_id = $1
                ORDER BY updated_at DESC
            """
            return await self._fetch(sql, user_id, op_label="get_positions_user")
        sql = "SELECT * FROM positions ORDER BY updated_at DESC"
        return await self._fetch(sql, op_label="get_positions")

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

    # ── Wallet state persistence ──────────────────────────────────────────────

    async def save_wallet_state(self, cash: float, locked: float, equity: float) -> bool:
        """Append a wallet state snapshot.

        Args:
            cash:   Available (unlocked) cash in USD.
            locked: Funds reserved for open positions.
            equity: Total portfolio value (cash + locked).

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO wallet_state (cash, locked, equity, snapshot_at)
            VALUES ($1, $2, $3, $4)
        """
        return await self._execute(
            sql,
            float(cash),
            float(locked),
            float(equity),
            time.time(),
            op_label="save_wallet_state",
        )

    async def load_latest_wallet_state(self) -> Optional[Dict[str, Any]]:
        """Retrieve the most recently persisted wallet state.

        Returns:
            Dict with keys ``cash``, ``locked``, ``equity``, ``snapshot_at``,
            or ``None`` if no snapshot exists.
        """
        sql = "SELECT cash, locked, equity, snapshot_at FROM wallet_state ORDER BY snapshot_at DESC LIMIT 1"
        rows = await self._fetch(sql, op_label="load_latest_wallet_state")
        if rows:
            row = rows[0]
            log.info(
                "wallet_state_loaded_from_db",
                cash=row["cash"],
                locked=row["locked"],
                equity=row["equity"],
            )
            return dict(row)
        return None

    # ── Paper positions persistence ───────────────────────────────────────────

    async def upsert_paper_position(self, position: Dict[str, Any]) -> bool:
        """Upsert a paper position record.

        Expected keys: market_id, side, size, entry_price, current_price,
            unrealized_pnl, status, opened_at, closed_at, trade_ids.

        Args:
            position: Position data dict.

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO paper_positions (
                market_id, side, size, entry_price, current_price,
                unrealized_pnl, status, opened_at, closed_at, trade_ids, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (market_id) DO UPDATE
                SET side          = EXCLUDED.side,
                    size          = EXCLUDED.size,
                    entry_price   = EXCLUDED.entry_price,
                    current_price = EXCLUDED.current_price,
                    unrealized_pnl= EXCLUDED.unrealized_pnl,
                    status        = EXCLUDED.status,
                    opened_at     = EXCLUDED.opened_at,
                    closed_at     = EXCLUDED.closed_at,
                    trade_ids     = EXCLUDED.trade_ids,
                    updated_at    = EXCLUDED.updated_at
        """
        args = (
            str(position.get("market_id", "")),
            str(position.get("side", "")),
            float(position.get("size", 0.0)),
            float(position.get("entry_price", 0.0)),
            float(position.get("current_price", 0.0)),
            float(position.get("unrealized_pnl", 0.0)),
            str(position.get("status", "OPEN")),
            float(position.get("opened_at", time.time())),
            position.get("closed_at"),  # may be None
            json.dumps(position.get("trade_ids", [])),
            time.time(),
        )
        return await self._execute(sql, *args, op_label="upsert_paper_position")

    async def load_open_paper_positions(self) -> List[Dict[str, Any]]:
        """Load all paper positions with status='OPEN'.

        Returns:
            List of position dicts with keys matching :class:`~core.positions.PaperPosition`.
        """
        sql = "SELECT * FROM paper_positions WHERE status = 'OPEN' ORDER BY opened_at ASC"
        rows = await self._fetch(sql, op_label="load_open_paper_positions")
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("trade_ids"), str):
                try:
                    d["trade_ids"] = json.loads(d["trade_ids"])
                except Exception:
                    d["trade_ids"] = []
            result.append(d)
        if result:
            log.info("paper_positions_loaded_from_db", count=len(result))
        return result

    async def delete_paper_position(self, market_id: str) -> bool:
        """Delete a paper position record (called on close).

        Args:
            market_id: Polymarket condition ID.

        Returns:
            True on success, False on error.
        """
        sql = "DELETE FROM paper_positions WHERE market_id = $1"
        return await self._execute(sql, market_id, op_label="delete_paper_position")

    # ── Trade ledger persistence ──────────────────────────────────────────────

    async def insert_ledger_entry(self, entry: Dict[str, Any]) -> bool:
        """Append a trade ledger entry.  Idempotent: ON CONFLICT DO NOTHING.

        Expected keys: trade_id, market_id, action, price, size, fee,
            realized_pnl (optional), ledger_ts.

        Args:
            entry: Ledger entry data dict.

        Returns:
            True on success, False on error.
        """
        sql = """
            INSERT INTO trade_ledger (
                trade_id, market_id, action, price, size, fee,
                realized_pnl, ledger_ts, inserted_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (trade_id) DO NOTHING
        """
        realized_pnl = entry.get("realized_pnl")
        args = (
            str(entry.get("trade_id", "")),
            str(entry.get("market_id", "")),
            str(entry.get("action", "")),
            float(entry.get("price", 0.0)),
            float(entry.get("size", 0.0)),
            float(entry.get("fee", 0.0)),
            float(realized_pnl) if realized_pnl is not None else None,
            str(entry.get("ledger_ts", "") or entry.get("timestamp", "")),
            time.time(),
        )
        return await self._execute(sql, *args, op_label="insert_ledger_entry")

    async def load_ledger_entries(
        self, market_id: Optional[str] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Load trade ledger entries.

        Args:
            market_id: If given, filter to this market.
            limit:     Max rows to return.

        Returns:
            List of ledger entry dicts ordered by inserted_at ASC.
        """
        if market_id:
            sql = """
                SELECT * FROM trade_ledger
                WHERE market_id = $1
                ORDER BY inserted_at ASC LIMIT $2
            """
            return await self._fetch(sql, market_id, limit, op_label="load_ledger_entries_market")
        sql = "SELECT * FROM trade_ledger ORDER BY inserted_at ASC LIMIT $1"
        return await self._fetch(sql, limit, op_label="load_ledger_entries")

    # ── Strategy toggle state ─────────────────────────────────────────────────

    async def load_strategy_state(self) -> Dict[str, bool]:
        """Load all strategy toggle states from the DB.

        Returns:
            Dict mapping strategy name → active bool.
            Empty dict on DB error (caller should fall back to defaults).
        """
        sql = "SELECT strategy, active FROM strategy_state"
        rows = await self._fetch(sql, op_label="load_strategy_state")
        state: Dict[str, bool] = {}
        for row in rows:
            state[str(row["strategy"])] = bool(row["active"])
        if state:
            log.info("strategy_state_loaded_from_db", state=state)
        return state

    async def save_strategy_state(self, state: Dict[str, bool]) -> bool:
        """Persist strategy toggle state with UPSERT semantics.

        Each strategy is upserted so the table always reflects the current
        in-memory state.  Idempotent — safe to call on every toggle.

        Args:
            state: Dict mapping strategy name → active bool.

        Returns:
            True if all upserts succeeded, False if any failed.
        """
        if not state:
            return True

        sql = """
            INSERT INTO strategy_state (strategy, active, updated_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (strategy) DO UPDATE
                SET active     = EXCLUDED.active,
                    updated_at = EXCLUDED.updated_at
        """
        now = time.time()
        all_ok = True
        for strategy, active in state.items():
            ok = await self._execute(
                sql,
                str(strategy),
                bool(active),
                now,
                op_label="save_strategy_state",
            )
            if not ok:
                all_ok = False

        if all_ok:
            log.info("strategy_state_saved_to_db", state=state)
        else:
            log.warning("strategy_state_partial_save_failure", state=state)
        return all_ok

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


log.info("db_import_ok")
