"""
SQLite state manager via aiosqlite.
Tables: portfolio, trades
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
    opened_at: float   # unix timestamp


class StateManager:
    def __init__(self, db_path: str, initial_balance: float) -> None:
        """Initialise with DB path and starting paper balance."""
        self.db_path = db_path
        self.initial_balance = initial_balance
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Create DB directory, connect, and run schema migrations."""
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
                pnl REAL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                opened_at REAL NOT NULL,
                closed_at REAL
            )
        """)
        await self._db.commit()

        # Init balance if not set
        async with self._db.execute("SELECT balance FROM portfolio WHERE id=1") as cur:
            row = await cur.fetchone()
        if row is None:
            await self._db.execute(
                "INSERT INTO portfolio (id, balance) VALUES (1, ?)",
                (self.initial_balance,),
            )
            await self._db.commit()
            log.info("balance_initialized", balance=self.initial_balance)

    async def get_balance(self) -> float:
        """Return current paper balance."""
        assert self._db
        async with self._db.execute("SELECT balance FROM portfolio WHERE id=1") as cur:
            row = await cur.fetchone()
        return float(row[0]) if row else self.initial_balance

    async def update_balance(self, new_balance: float) -> None:
        """Overwrite the current paper balance."""
        assert self._db
        await self._db.execute(
            "UPDATE portfolio SET balance=? WHERE id=1", (new_balance,)
        )
        await self._db.commit()

    async def save_trade(self, trade: OpenTrade) -> None:
        """Persist a new OPEN trade."""
        assert self._db
        await self._db.execute(
            """
            INSERT INTO trades
               (trade_id, market_id, question, outcome, entry_price, size, ev, status, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                trade.trade_id,
                trade.market_id,
                trade.question,
                trade.outcome,
                trade.entry_price,
                trade.size,
                trade.ev,
                trade.opened_at,
            ),
        )
        await self._db.commit()
        log.info("trade_saved", trade_id=trade.trade_id)

    async def get_open_trade(self) -> OpenTrade | None:
        """Return the single open trade, or None."""
        assert self._db
        async with self._db.execute(
            "SELECT trade_id, market_id, question, outcome, entry_price, size, ev, opened_at "
            "FROM trades WHERE status='OPEN' LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return OpenTrade(
            trade_id=row[0],
            market_id=row[1],
            question=row[2],
            outcome=row[3],
            entry_price=row[4],
            size=row[5],
            ev=row[6],
            opened_at=row[7],
        )

    async def close_trade(
        self, trade_id: str, exit_price: float, pnl: float
    ) -> None:
        """Mark a trade as CLOSED with exit price and PnL."""
        assert self._db
        await self._db.execute(
            """
            UPDATE trades
               SET status='CLOSED', exit_price=?, pnl=?, closed_at=?
               WHERE trade_id=?
            """,
            (exit_price, pnl, time.time(), trade_id),
        )
        await self._db.commit()
        log.info("trade_closed", trade_id=trade_id, pnl=round(pnl, 2))

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
