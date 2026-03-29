"""Persistent state manager with event logging and correlation tracking."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Optional

import aiosqlite
import structlog

from .event_bus import EventEnvelope

log = structlog.get_logger()


@dataclass
class OpenTrade:
    """Represents an active paper trade."""

    market_id: str
    question: str
    entry_price: float
    size: float
    kelly_f: float
    ev: float
    fee: float
    entry_time: float
    correlation_id: str
    exit_price: Optional[float] = None
    exit_time: Optional[float] = None
    pnl: Optional[float] = None


class StateManager:
    """SQLite-backed state manager (WAL mode) for trades and events."""

    def __init__(self, db_path: str = "polyquantbot_phase4.db") -> None:
        """Initialise with database path."""
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        """Open database connection and create tables."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()
        log.info("state_manager_initialized", db=self._db_path)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()

    def _conn(self) -> aiosqlite.Connection:
        """Return active DB connection or raise."""
        if self._db is None:
            raise RuntimeError("StateManager.init() must be called before use")
        return self._db

    async def _create_tables(self) -> None:
        """Create all required tables."""
        db = self._conn()
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                question TEXT,
                entry_price REAL,
                size REAL,
                kelly_f REAL,
                ev REAL,
                fee REAL,
                entry_time REAL,
                exit_price REAL,
                exit_time REAL,
                pnl REAL,
                correlation_id TEXT,
                status TEXT DEFAULT 'open'
            );

            CREATE TABLE IF NOT EXISTS performance_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at REAL,
                total_trades INTEGER,
                winning_trades INTEGER,
                total_pnl REAL,
                win_rate REAL,
                avg_ev REAL
            );

            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_id TEXT,
                event_type TEXT,
                source TEXT,
                market_id TEXT,
                timestamp_ms INTEGER,
                payload TEXT
            );

            CREATE TABLE IF NOT EXISTS failed_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_id TEXT,
                event_type TEXT,
                error TEXT,
                timestamp_ms INTEGER,
                payload TEXT
            );
        """)
        await db.commit()

    async def log_event(self, envelope: EventEnvelope) -> None:
        """Persist every event envelope to event_log."""
        db = self._conn()
        await db.execute(
            """
            INSERT INTO event_log
            (correlation_id, event_type, source, market_id, timestamp_ms, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                envelope.correlation_id,
                envelope.event_type,
                envelope.source,
                envelope.market_id,
                envelope.timestamp_ms,
                json.dumps(envelope.payload),
            ),
        )
        await db.commit()

    async def save_failed_event(self, envelope: EventEnvelope, error: str) -> None:
        """Record a failed event for debugging."""
        db = self._conn()
        await db.execute(
            """
            INSERT INTO failed_events
            (correlation_id, event_type, error, timestamp_ms, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                envelope.correlation_id,
                envelope.event_type,
                error,
                envelope.timestamp_ms,
                json.dumps(envelope.payload),
            ),
        )
        await db.commit()

    async def get_balance(self) -> float:
        """Return current paper balance."""
        db = self._conn()
        async with db.execute(
            "SELECT SUM(pnl) FROM trades WHERE status = 'closed'"
        ) as cur:
            row = await cur.fetchone()
            realized_pnl = row[0] or 0.0
        return realized_pnl  # caller adds initial_balance

    async def save_trade(self, trade: OpenTrade) -> None:
        """Insert a new open trade."""
        db = self._conn()
        await db.execute(
            """
            INSERT INTO trades
            (market_id, question, entry_price, size, kelly_f, ev, fee,
             entry_time, correlation_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                trade.market_id,
                trade.question,
                trade.entry_price,
                trade.size,
                trade.kelly_f,
                trade.ev,
                trade.fee,
                trade.entry_time,
                trade.correlation_id,
            ),
        )
        await db.commit()

    async def close_trade(
        self,
        market_id: str,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Mark trade as closed with exit data."""
        db = self._conn()
        await db.execute(
            """
            UPDATE trades
            SET status = 'closed', exit_price = ?, exit_time = ?, pnl = ?
            WHERE market_id = ? AND status = 'open'
            """,
            (exit_price, time.time(), pnl, market_id),
        )
        await db.commit()

    async def get_open_positions(self) -> list[OpenTrade]:
        """Return all currently open trades."""
        db = self._conn()
        async with db.execute(
            "SELECT market_id, question, entry_price, size, kelly_f, ev, fee, "
            "entry_time, correlation_id FROM trades WHERE status = 'open'"
        ) as cur:
            rows = await cur.fetchall()
        return [
            OpenTrade(
                market_id=r[0],
                question=r[1],
                entry_price=r[2],
                size=r[3],
                kelly_f=r[4],
                ev=r[5],
                fee=r[6],
                entry_time=r[7],
                correlation_id=r[8],
            )
            for r in rows
        ]

    async def record_performance(
        self,
        total_trades: int,
        winning_trades: int,
        total_pnl: float,
        win_rate: float,
        avg_ev: float,
    ) -> None:
        """Snapshot current performance metrics."""
        db = self._conn()
        await db.execute(
            """
            INSERT INTO performance_stats
            (recorded_at, total_trades, winning_trades, total_pnl, win_rate, avg_ev)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (time.time(), total_trades, winning_trades, total_pnl, win_rate, avg_ev),
        )
        await db.commit()

    async def get_performance(self) -> dict:
        """Return latest performance snapshot."""
        db = self._conn()
        async with db.execute(
            "SELECT total_trades, winning_trades, total_pnl, win_rate, avg_ev "
            "FROM performance_stats ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        return {
            "total_trades": row[0],
            "winning_trades": row[1],
            "total_pnl": row[2],
            "win_rate": row[3],
            "avg_ev": row[4],
        }
