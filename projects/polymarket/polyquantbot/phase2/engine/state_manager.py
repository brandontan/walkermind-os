"""
State manager — Phase 2.
Supports multiple concurrent open positions.
Adds performance_stats table.
"""

import os
import time
import aiosqlite
import structlog
from dataclasses import dataclass

log = structlog.get_logger()


@dataclass
class OpenTrade:
    trade_id: str
    market_id: str
    question: str
    outcome: str
    entry_price: float
    size: float
    ev: float
    fee: float
    opened_at: float


class StateManager:
    def __init__(self, db_path: str, initial_balance: float) -> None:
        """Initialise with DB path and starting paper balance."""
        self.db_path = db_path
        self.initial_balance = initial_balance
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Create DB directory, connect, run schema migrations, seed initial rows."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY,
                balance REAL NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                question TEXT NOT NULL,
                outcome TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                size REAL NOT NULL,
                ev REAL NOT NULL,
                fee REAL NOT NULL DEFAULT 0,
                pnl REAL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                opened_at REAL NOT NULL,
                closed_at REAL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS performance_stats (
                id INTEGER PRIMARY KEY,
                trade_count INTEGER NOT NULL DEFAULT 0,
                win_count INTEGER NOT NULL DEFAULT 0,
                total_pnl REAL NOT NULL DEFAULT 0,
                total_ev REAL NOT NULL DEFAULT 0
            )
        """)
        await self._db.commit()

        async with self._db.execute("SELECT balance FROM portfolio WHERE id=1") as cur:
            row = await cur.fetchone()
        if row is None:
            await self._db.execute(
                "INSERT INTO portfolio (id, balance) VALUES (1, ?)",
                (self.initial_balance,),
            )
            await self._db.commit()

        async with self._db.execute("SELECT id FROM performance_stats WHERE id=1") as cur:
            row = await cur.fetchone()
        if row is None:
            await self._db.execute("INSERT INTO performance_stats (id) VALUES (1)")
            await self._db.commit()

        log.info("state_manager_initialized", db_path=self.db_path)

    async def get_balance(self) -> float:
        """Return current paper balance."""
        if not self._db:
            raise RuntimeError("StateManager.init() must be called before use")
        async with self._db.execute("SELECT balance FROM portfolio WHERE id=1") as cur:
            row = await cur.fetchone()
        return float(row[0]) if row else self.initial_balance

    async def update_balance(self, new_balance: float) -> None:
        """Overwrite the current paper balance."""
        if not self._db:
            raise RuntimeError("StateManager.init() must be called before use")
        await self._db.execute(
            "UPDATE portfolio SET balance=? WHERE id=1", (new_balance,)
        )
        await self._db.commit()

    async def save_trade(self, trade: OpenTrade) -> None:
        """Persist a new OPEN trade."""
        if not self._db:
            raise RuntimeError("StateManager.init() must be called before use")
        await self._db.execute(
            """
            INSERT INTO trades
               (trade_id, market_id, question, outcome, entry_price, size, ev, fee, status, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                trade.trade_id,
                trade.market_id,
                trade.question,
                trade.outcome,
                trade.entry_price,
                trade.size,
                trade.ev,
                trade.fee,
                trade.opened_at,
            ),
        )
        await self._db.commit()
        log.info("trade_saved", trade_id=trade.trade_id, market_id=trade.market_id)

    async def get_open_positions(self) -> list[OpenTrade]:
        """Return all currently open positions."""
        if not self._db:
            raise RuntimeError("StateManager.init() must be called before use")
        async with self._db.execute(
            "SELECT trade_id, market_id, question, outcome, entry_price, size, ev, fee, opened_at "
            "FROM trades WHERE status='OPEN'"
        ) as cur:
            rows = await cur.fetchall()
        return [
            OpenTrade(
                trade_id=r[0], market_id=r[1], question=r[2], outcome=r[3],
                entry_price=r[4], size=r[5], ev=r[6], fee=r[7], opened_at=r[8],
            )
            for r in rows
        ]

    async def close_trade(
        self, trade_id: str, exit_price: float, pnl: float
    ) -> None:
        """Mark a trade as CLOSED with exit price and PnL."""
        if not self._db:
            raise RuntimeError("StateManager.init() must be called before use")
        await self._db.execute(
            """
            UPDATE trades
               SET status='CLOSED', exit_price=?, pnl=?, closed_at=?
               WHERE trade_id=?
            """,
            (exit_price, pnl, time.time(), trade_id),
        )
        await self._db.commit()
        log.info("trade_closed_db", trade_id=trade_id, pnl=round(pnl, 4))

    async def record_performance(self, pnl: float, ev: float, is_win: bool) -> None:
        """Increment performance_stats counters."""
        if not self._db:
            raise RuntimeError("StateManager.init() must be called before use")
        await self._db.execute(
            """
            UPDATE performance_stats SET
               trade_count = trade_count + 1,
               win_count   = win_count + ?,
               total_pnl   = total_pnl + ?,
               total_ev    = total_ev + ?
               WHERE id=1
            """,
            (1 if is_win else 0, pnl, ev),
        )
        await self._db.commit()

    async def get_performance(self) -> dict:
        """Return current performance stats as a dict."""
        if not self._db:
            raise RuntimeError("StateManager.init() must be called before use")
        async with self._db.execute(
            "SELECT trade_count, win_count, total_pnl, total_ev FROM performance_stats WHERE id=1"
        ) as cur:
            row = await cur.fetchone()
        if not row or row[0] == 0:
            return {"trade_count": 0, "win_count": 0, "total_pnl": 0.0, "winrate": 0.0, "avg_pnl": 0.0, "total_ev": 0.0}
        trade_count, win_count, total_pnl, total_ev = row
        return {
            "trade_count": trade_count,
            "win_count": win_count,
            "total_pnl": round(total_pnl, 2),
            "winrate": round(win_count / trade_count * 100, 1),
            "avg_pnl": round(total_pnl / trade_count, 2),
            "total_ev": round(total_ev, 4),
        }

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
