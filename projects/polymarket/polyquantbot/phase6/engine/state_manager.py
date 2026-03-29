"""Persistent state manager — Phase 6. Unchanged from Phase 5.

SQLite-backed (WAL mode). Manages balance, open trades, performance log,
event log, and failed events.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import aiosqlite
import structlog

from .event_bus import EventEnvelope

log = structlog.get_logger()


@dataclass
class OpenTrade:
    """Represents an active paper trade."""

    trade_id: str
    market_id: str
    question: str
    outcome: str            # "YES" | "NO"
    entry_price: float
    size: float
    ev: float
    fee: float
    opened_at: float
    correlation_id: str
    strategy: str = "bayesian"
    exit_price: Optional[float] = None
    closed_at: Optional[float] = None
    pnl: Optional[float] = None


class StateManager:
    """SQLite-backed state manager (WAL mode) for Phase 6."""

    def __init__(self, db_path: str = "phase6.db", initial_balance: float = 1000.0) -> None:
        """Initialise with database path and initial paper balance."""
        self._db_path = db_path
        self._initial_balance = initial_balance
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        """Open database connection and create tables."""
        import os
        os.makedirs(
            os.path.dirname(self._db_path) if os.path.dirname(self._db_path) else ".",
            exist_ok=True,
        )
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()
        async with self._db.execute("SELECT balance FROM account LIMIT 1") as cur:
            row = await cur.fetchone()
        if not row:
            await self._db.execute(
                "INSERT INTO account (balance) VALUES (?)", (self._initial_balance,)
            )
            await self._db.commit()
        log.info("state_manager_initialized", db=self._db_path)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("StateManager.init() must be called before use")
        return self._db

    async def _create_tables(self) -> None:
        db = self._conn()
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                question TEXT,
                outcome TEXT,
                entry_price REAL,
                size REAL,
                ev REAL,
                fee REAL,
                opened_at REAL,
                exit_price REAL,
                closed_at REAL,
                pnl REAL,
                correlation_id TEXT,
                strategy TEXT DEFAULT 'bayesian',
                status TEXT DEFAULT 'open'
            );
            CREATE TABLE IF NOT EXISTS performance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at REAL,
                pnl REAL,
                ev REAL,
                is_win INTEGER
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
                event_type TEXT,
                correlation_id TEXT,
                payload TEXT,
                error TEXT,
                recorded_at REAL
            );
        """)
        await db.commit()

    async def get_balance(self) -> float:
        db = self._conn()
        async with db.execute("SELECT balance FROM account LIMIT 1") as cur:
            row = await cur.fetchone()
        return row[0] if row else self._initial_balance

    async def update_balance(self, balance: float) -> None:
        db = self._conn()
        await db.execute("UPDATE account SET balance = ? WHERE id = 1", (balance,))
        await db.commit()

    async def save_trade(self, trade: OpenTrade) -> None:
        db = self._conn()
        await db.execute(
            """INSERT OR IGNORE INTO trades
               (trade_id, market_id, question, outcome, entry_price, size, ev, fee,
                opened_at, correlation_id, strategy, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                trade.trade_id, trade.market_id, trade.question, trade.outcome,
                trade.entry_price, trade.size, trade.ev, trade.fee,
                trade.opened_at, trade.correlation_id, trade.strategy,
            ),
        )
        await db.commit()

    async def close_trade(self, trade_id: str, exit_price: float, pnl: float) -> None:
        db = self._conn()
        await db.execute(
            """UPDATE trades SET status='closed', exit_price=?, closed_at=?, pnl=?
               WHERE trade_id=? AND status='open'""",
            (exit_price, time.time(), pnl, trade_id),
        )
        await db.commit()

    async def get_open_positions(self) -> list[OpenTrade]:
        db = self._conn()
        async with db.execute(
            "SELECT trade_id, market_id, question, outcome, entry_price, size, ev, fee, "
            "opened_at, correlation_id, strategy FROM trades WHERE status='open'"
        ) as cur:
            rows = await cur.fetchall()
        return [
            OpenTrade(
                trade_id=r[0], market_id=r[1], question=r[2], outcome=r[3],
                entry_price=r[4], size=r[5], ev=r[6], fee=r[7],
                opened_at=r[8], correlation_id=r[9], strategy=r[10],
            )
            for r in rows
        ]

    async def record_performance(self, pnl: float, ev: float, is_win: bool) -> None:
        db = self._conn()
        await db.execute(
            "INSERT INTO performance_log (recorded_at, pnl, ev, is_win) VALUES (?, ?, ?, ?)",
            (time.time(), pnl, ev, int(is_win)),
        )
        await db.commit()

    async def get_performance(self) -> dict:
        db = self._conn()
        async with db.execute(
            "SELECT COUNT(*), SUM(is_win), SUM(pnl), AVG(pnl), SUM(ev) FROM performance_log"
        ) as cur:
            row = await cur.fetchone()
        if not row or not row[0]:
            return {"trade_count": 0, "winrate": 0.0, "total_pnl": 0.0,
                    "avg_pnl": 0.0, "ev_sum": 0.0}
        total, wins, total_pnl, avg_pnl, ev_sum = row
        return {
            "trade_count": total,
            "winrate": round((wins or 0) / total * 100, 2),
            "total_pnl": round(total_pnl or 0.0, 4),
            "avg_pnl": round(avg_pnl or 0.0, 4),
            "ev_sum": round(ev_sum or 0.0, 4),
        }

    async def log_event(self, envelope: EventEnvelope) -> None:
        db = self._conn()
        await db.execute(
            "INSERT INTO event_log (correlation_id, event_type, source, market_id, "
            "timestamp_ms, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (
                envelope.correlation_id, envelope.event_type, envelope.source,
                envelope.market_id, envelope.timestamp_ms, json.dumps(envelope.payload),
            ),
        )
        await db.commit()

    async def save_failed_event(
        self, event_type: str, correlation_id: str, payload: str, error: str
    ) -> None:
        db = self._conn()
        await db.execute(
            "INSERT INTO failed_events (event_type, correlation_id, payload, error, "
            "recorded_at) VALUES (?, ?, ?, ?, ?)",
            (event_type, correlation_id, payload, error, time.time()),
        )
        await db.commit()
