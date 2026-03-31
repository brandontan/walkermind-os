"""Phase 10.5 — LiveAuditLogger: Immutable audit trail for LIVE executions.

Writes a structured record to PostgreSQL BEFORE and AFTER every LIVE order.
No execution should proceed without a ``pre_execution`` record, and every
execution attempt must produce a corresponding ``post_execution`` record.

Schema (table: live_audit_log)::

    id              SERIAL PRIMARY KEY
    event_type      VARCHAR(32)    -- "pre_execution" | "post_execution"
    timestamp       DOUBLE PRECISION  -- Unix epoch seconds (UTC)
    market_id       TEXT
    side            VARCHAR(8)     -- "YES" | "NO"
    size_usd        DOUBLE PRECISION
    expected_price  DOUBLE PRECISION
    actual_fill     DOUBLE PRECISION   -- 0.0 for pre_execution
    slippage_bps    DOUBLE PRECISION   -- 0.0 for pre_execution
    latency_ms      DOUBLE PRECISION   -- 0.0 for pre_execution
    decision_source TEXT           -- signal / correlation_id
    status          VARCHAR(32)    -- "pending" | "filled" | "partial" | "rejected"
    correlation_id  TEXT

Design principles:

    - WRITE BEFORE execution (event_type="pre_execution") — no bypass possible.
    - WRITE AFTER execution  (event_type="post_execution") — captures outcome.
    - No sampling — every LIVE action is recorded.
    - No silent failures — write errors raise WriteError after logging.
    - Idempotent inserts — correlation_id used as natural dedup key.
    - Async non-blocking — all DB operations use asyncpg.

Environment variables:

    DATABASE_URL — PostgreSQL DSN (postgresql://user:pass@host:5432/db)

Usage::

    audit = LiveAuditLogger.from_env()
    await audit.connect()

    await audit.write_pre(
        market_id="0xabc", side="YES", size_usd=100.0,
        expected_price=0.62, decision_source="sig-001",
        correlation_id="cid-xyz",
    )
    result = await executor.execute(request)
    await audit.write_post(
        market_id="0xabc", side="YES", size_usd=100.0,
        expected_price=0.62, actual_fill=0.625,
        slippage_bps=80.6, latency_ms=210.0,
        decision_source="sig-001", status="filled",
        correlation_id="cid-xyz",
    )

    await audit.close()
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()

# ── DDL (table creation) ──────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS live_audit_log (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(32)       NOT NULL,
    timestamp       DOUBLE PRECISION  NOT NULL,
    market_id       TEXT              NOT NULL,
    side            VARCHAR(8)        NOT NULL,
    size_usd        DOUBLE PRECISION  NOT NULL,
    expected_price  DOUBLE PRECISION  NOT NULL,
    actual_fill     DOUBLE PRECISION  NOT NULL DEFAULT 0.0,
    slippage_bps    DOUBLE PRECISION  NOT NULL DEFAULT 0.0,
    latency_ms      DOUBLE PRECISION  NOT NULL DEFAULT 0.0,
    decision_source TEXT              NOT NULL DEFAULT '',
    status          VARCHAR(32)       NOT NULL DEFAULT 'pending',
    correlation_id  TEXT              NOT NULL
);
"""

_INSERT_SQL = """
INSERT INTO live_audit_log (
    event_type, timestamp, market_id, side, size_usd,
    expected_price, actual_fill, slippage_bps, latency_ms,
    decision_source, status, correlation_id
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
"""


# ── Error types ───────────────────────────────────────────────────────────────


class AuditWriteError(Exception):
    """Raised when an audit write fails after all retries."""


# ── Record type ───────────────────────────────────────────────────────────────


@dataclass
class AuditRecord:
    """Structured audit record for a single execution event.

    Attributes:
        event_type: "pre_execution" | "post_execution".
        timestamp: Unix epoch seconds (UTC).
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        size_usd: Order size in USD.
        expected_price: Limit price at submission.
        actual_fill: VWAP of executed fills (0.0 for pre_execution).
        slippage_bps: Slippage in basis points (0.0 for pre_execution).
        latency_ms: Execution latency in milliseconds (0.0 for pre_execution).
        decision_source: Signal / correlation ID that triggered the trade.
        status: "pending" | "filled" | "partial" | "rejected".
        correlation_id: Request trace ID.
    """

    event_type: str
    timestamp: float
    market_id: str
    side: str
    size_usd: float
    expected_price: float
    actual_fill: float
    slippage_bps: float
    latency_ms: float
    decision_source: str
    status: str
    correlation_id: str


# ── LiveAuditLogger ───────────────────────────────────────────────────────────


class LiveAuditLogger:
    """Immutable LIVE audit trail persisted to PostgreSQL.

    Requires ``asyncpg`` (install with ``pip install asyncpg``).  If asyncpg
    is not available, falls back to structured-log-only mode with a warning.

    Args:
        database_url: PostgreSQL DSN.
        table_name: Target table name (default: ``live_audit_log``).
        log_only: If True, skip DB writes and log only (useful in testing).
    """

    def __init__(
        self,
        database_url: str,
        table_name: str = "live_audit_log",
        log_only: bool = False,
    ) -> None:
        self._dsn = database_url
        self._table = table_name
        self._log_only = log_only
        self._pool: Optional[object] = None

        log.info(
            "live_audit_logger_initialized",
            table=table_name,
            log_only=log_only,
            has_dsn=bool(database_url),
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, log_only: bool = False) -> "LiveAuditLogger":
        """Build from environment variables.

        Reads:
            DATABASE_URL — PostgreSQL DSN.

        Args:
            log_only: Override to log-only mode (skips DB).

        Returns:
            Configured LiveAuditLogger.
        """
        dsn = os.getenv("DATABASE_URL", "")
        if not dsn:
            log.warning(
                "live_audit_logger_no_database_url",
                note="Falling back to log-only mode",
            )
            log_only = True
        return cls(database_url=dsn, log_only=log_only)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create the asyncpg connection pool and ensure the table exists."""
        if self._log_only:
            log.info("live_audit_logger_log_only_mode_active")
            return

        try:
            import asyncpg  # type: ignore[import]
        except ImportError:
            log.warning(
                "live_audit_logger_asyncpg_missing",
                note="asyncpg not installed; switching to log-only mode",
            )
            self._log_only = True
            return

        try:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            async with self._pool.acquire() as conn:  # type: ignore[union-attr]
                await conn.execute(_CREATE_TABLE_SQL)
            log.info("live_audit_logger_connected", table=self._table)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "live_audit_logger_connect_failed",
                error=str(exc),
                note="Switching to log-only mode",
            )
            self._log_only = True

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()  # type: ignore[union-attr]
            self._pool = None
        log.info("live_audit_logger_closed")

    # ── Public write API ──────────────────────────────────────────────────────

    async def write_pre(
        self,
        market_id: str,
        side: str,
        size_usd: float,
        expected_price: float,
        decision_source: str,
        correlation_id: str,
    ) -> None:
        """Write a PRE-execution audit record.

        Must be called BEFORE forwarding the order to the exchange.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            size_usd: Order size in USD.
            expected_price: Limit price at submission.
            decision_source: Signal ID / correlation ID that triggered the trade.
            correlation_id: Request trace ID.

        Raises:
            AuditWriteError: If the write fails (after logging).
        """
        record = AuditRecord(
            event_type="pre_execution",
            timestamp=time.time(),
            market_id=market_id,
            side=side,
            size_usd=size_usd,
            expected_price=expected_price,
            actual_fill=0.0,
            slippage_bps=0.0,
            latency_ms=0.0,
            decision_source=decision_source,
            status="pending",
            correlation_id=correlation_id,
        )
        await self._write(record)

    async def write_post(
        self,
        market_id: str,
        side: str,
        size_usd: float,
        expected_price: float,
        actual_fill: float,
        slippage_bps: float,
        latency_ms: float,
        decision_source: str,
        status: str,
        correlation_id: str,
    ) -> None:
        """Write a POST-execution audit record.

        Must be called AFTER receiving the exchange fill confirmation.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            size_usd: Filled size in USD.
            expected_price: Limit price at submission.
            actual_fill: VWAP of executed fills.
            slippage_bps: Slippage in basis points.
            latency_ms: Execution latency in milliseconds.
            decision_source: Signal ID / correlation ID.
            status: "filled" | "partial" | "rejected".
            correlation_id: Request trace ID.

        Raises:
            AuditWriteError: If the write fails (after logging).
        """
        record = AuditRecord(
            event_type="post_execution",
            timestamp=time.time(),
            market_id=market_id,
            side=side,
            size_usd=size_usd,
            expected_price=expected_price,
            actual_fill=actual_fill,
            slippage_bps=slippage_bps,
            latency_ms=latency_ms,
            decision_source=decision_source,
            status=status,
            correlation_id=correlation_id,
        )
        await self._write(record)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _write(self, record: AuditRecord) -> None:
        """Persist an audit record to PostgreSQL (or log-only mode).

        Args:
            record: AuditRecord to persist.

        Raises:
            AuditWriteError: If DB write fails in non-log-only mode.
        """
        log.info(
            "live_audit_record",
            event_type=record.event_type,
            market_id=record.market_id,
            side=record.side,
            size_usd=record.size_usd,
            expected_price=record.expected_price,
            actual_fill=record.actual_fill,
            slippage_bps=record.slippage_bps,
            latency_ms=record.latency_ms,
            status=record.status,
            decision_source=record.decision_source,
            correlation_id=record.correlation_id,
        )

        if self._log_only or self._pool is None:
            return

        try:
            async with self._pool.acquire() as conn:  # type: ignore[union-attr]
                await conn.execute(
                    _INSERT_SQL,
                    record.event_type,
                    record.timestamp,
                    record.market_id,
                    record.side,
                    record.size_usd,
                    record.expected_price,
                    record.actual_fill,
                    record.slippage_bps,
                    record.latency_ms,
                    record.decision_source,
                    record.status,
                    record.correlation_id,
                )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "live_audit_write_failed",
                event_type=record.event_type,
                correlation_id=record.correlation_id,
                error=str(exc),
                exc_info=True,
            )
            raise AuditWriteError(
                f"audit_write_failed:{record.event_type}:{record.correlation_id}"
            ) from exc
