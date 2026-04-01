"""Phase 11 — LiveTradeLogger: Structured logging for every real LIVE order.

Writes a REAL_TRADE event to both the structured log stream and an optional
append-only JSONL file on disk for offline analysis.

Event schema::

    {
        "type":      "REAL_TRADE",
        "market":    str,        -- Polymarket condition ID
        "side":      str,        -- "YES" | "NO"
        "price":     float,      -- execution price
        "size_usd":  float,      -- filled size in USD
        "timestamp": int         -- Unix epoch milliseconds (UTC)
    }

Design:
    - Thread-safe: protected by asyncio.Lock.
    - Append-only: JSONL file is never truncated or overwritten.
    - Zero silent failure: all write errors are logged; exceptions re-raised
      so the caller can decide to continue or halt.
    - Idempotent construction: calling log_trade() multiple times with the
      same correlation_id is safe — each call produces one log line.
    - Structured JSON logging on every call.

Usage::

    logger = LiveTradeLogger()
    await logger.log_trade(
        market="0xabc123",
        side="YES",
        price=0.62,
        size_usd=50.0,
        correlation_id="cid-001",
    )
    await logger.close()
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_LOG_FILE: str = "live_trades.jsonl"
_TRADE_EVENT_TYPE: str = "REAL_TRADE"


# ── Trade event dataclass ─────────────────────────────────────────────────────


@dataclass
class LiveTradeEvent:
    """Structured record for a single LIVE trade execution.

    Attributes:
        type: Always "REAL_TRADE".
        market: Polymarket condition ID.
        side: "YES" | "NO".
        price: Execution price.
        size_usd: Filled size in USD.
        timestamp: Unix epoch milliseconds (UTC).
        correlation_id: Request trace ID (not emitted to file schema).
        status: Execution status ("filled" | "partial" | "rejected").
    """

    type: str
    market: str
    side: str
    price: float
    size_usd: float
    timestamp: int
    correlation_id: str = ""
    status: str = "filled"

    def to_dict(self) -> dict:
        """Return the canonical event dict (matches interface schema).

        Returns:
            Dict with keys: type, market, side, price, size_usd, timestamp.
        """
        return {
            "type": self.type,
            "market": self.market,
            "side": self.side,
            "price": self.price,
            "size_usd": self.size_usd,
            "timestamp": self.timestamp,
        }


# ── LiveTradeLogger ───────────────────────────────────────────────────────────


class LiveTradeLogger:
    """Writes every LIVE trade execution to structured log and JSONL file.

    Args:
        log_file: Path to the append-only JSONL output file.
                  If None or empty string, file logging is disabled.
        include_correlation_id: If True, include correlation_id in the file record.
    """

    def __init__(
        self,
        log_file: Optional[str] = _DEFAULT_LOG_FILE,
        include_correlation_id: bool = False,
    ) -> None:
        self._log_file = log_file or ""
        self._include_cid = include_correlation_id
        self._lock: asyncio.Lock = asyncio.Lock()
        self._trade_count: int = 0

        log.info(
            "live_trade_logger_initialized",
            log_file=self._log_file or "disabled",
            file_logging_enabled=bool(self._log_file),
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "LiveTradeLogger":
        """Build from environment variables.

        Reads:
            LIVE_TRADE_LOG_FILE — path to JSONL output file.
                                  Defaults to ``live_trades.jsonl``.

        Returns:
            Configured LiveTradeLogger.
        """
        log_file = os.getenv("LIVE_TRADE_LOG_FILE", _DEFAULT_LOG_FILE).strip()
        return cls(log_file=log_file or None)

    # ── Primary API ───────────────────────────────────────────────────────────

    async def log_trade(
        self,
        market: str,
        side: str,
        price: float,
        size_usd: float,
        correlation_id: str = "",
        status: str = "filled",
    ) -> LiveTradeEvent:
        """Log a real LIVE trade execution.

        Emits a structured log event and appends to the JSONL file.

        Args:
            market: Polymarket condition ID.
            side: "YES" | "NO".
            price: Execution price.
            size_usd: Filled size in USD.
            correlation_id: Request trace ID.
            status: Execution status ("filled" | "partial" | "rejected").

        Returns:
            LiveTradeEvent that was logged.

        Raises:
            OSError: If the JSONL file cannot be written (after logging the error).
        """
        ts_ms = int(time.time() * 1000)

        event = LiveTradeEvent(
            type=_TRADE_EVENT_TYPE,
            market=market,
            side=side,
            price=price,
            size_usd=size_usd,
            timestamp=ts_ms,
            correlation_id=correlation_id,
            status=status,
        )

        # Structured log — always emitted
        log.info(
            "live_trade_executed",
            type=event.type,
            market=market,
            side=side,
            price=price,
            size_usd=size_usd,
            timestamp=ts_ms,
            status=status,
            correlation_id=correlation_id,
        )

        # File append — only when configured
        if self._log_file:
            await self._append_to_file(event)

        async with self._lock:
            self._trade_count += 1

        return event

    async def close(self) -> None:
        """Flush and close the trade log (no-op for pure file appends).

        Included for lifecycle symmetry with other loggers in the system.
        """
        log.info(
            "live_trade_logger_closed",
            total_trades_logged=self._trade_count,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def trade_count(self) -> int:
        """Total number of live trade events logged in this session."""
        return self._trade_count

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _append_to_file(self, event: LiveTradeEvent) -> None:
        """Append the event as a JSON line to the log file.

        Args:
            event: LiveTradeEvent to serialise and write.

        Raises:
            OSError: On write failure.
        """
        record = event.to_dict()
        if self._include_cid:
            record["correlation_id"] = event.correlation_id

        line = json.dumps(record, separators=(",", ":")) + "\n"

        async with self._lock:
            try:
                # Use run_in_executor to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _write_line, self._log_file, line)
            except OSError as exc:
                log.error(
                    "live_trade_logger_file_write_failed",
                    log_file=self._log_file,
                    correlation_id=event.correlation_id,
                    error=str(exc),
                    exc_info=True,
                )
                raise


# ── Module helpers ────────────────────────────────────────────────────────────


def _write_line(path: str, line: str) -> None:
    """Append a single line to a file (blocking I/O — run in executor).

    Args:
        path: File path.
        line: Line to append (should end with newline).
    """
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
