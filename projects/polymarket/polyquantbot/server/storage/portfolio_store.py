"""Portfolio store — PostgreSQL persistence for portfolio snapshots.

Reads from existing tables (trades, paper_positions) to compute portfolio
state, and writes point-in-time snapshots to portfolio_snapshots.

Design:
    - All operations are async (asyncpg pool).
    - Reads are non-destructive; writes are idempotent on snapshot_id.
    - Fail-safe: DB failures are logged and return safe defaults — never crash.
    - Full type hints throughout.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from projects.polymarket.polyquantbot.server.schemas.portfolio import (
    PortfolioPosition,
    PortfolioSnapshot,
)

log = structlog.get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _epoch(dt: datetime) -> float:
    return dt.timestamp()


class PortfolioStore:
    """Async PostgreSQL store for portfolio management.

    Args:
        db: Connected DatabaseClient instance.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Snapshot persistence ──────────────────────────────────────────────────

    async def insert_snapshot(self, snapshot: PortfolioSnapshot) -> bool:
        """Persist a portfolio snapshot.  Idempotent on snapshot_id.

        Returns:
            True on insert (or duplicate skip), False on error.
        """
        sql = """
            INSERT INTO portfolio_snapshots (
                snapshot_id, tenant_id, user_id, wallet_id,
                realized_pnl, unrealized_pnl, net_pnl,
                cash_usd, locked_usd, equity_usd,
                drawdown, exposure_pct, position_count,
                mode, recorded_at, metadata
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7,
                $8, $9, $10,
                $11, $12, $13,
                $14, $15, $16
            )
            ON CONFLICT (snapshot_id) DO NOTHING
        """
        try:
            pool = self._db._pool
            if pool is None:
                log.warning("portfolio_store_insert_no_pool")
                return False
            async with pool.acquire() as conn:
                await conn.execute(
                    sql,
                    snapshot.snapshot_id,
                    snapshot.tenant_id,
                    snapshot.user_id,
                    snapshot.wallet_id,
                    snapshot.realized_pnl,
                    snapshot.unrealized_pnl,
                    snapshot.net_pnl,
                    snapshot.cash_usd,
                    snapshot.locked_usd,
                    snapshot.equity_usd,
                    snapshot.drawdown,
                    snapshot.exposure_pct,
                    snapshot.position_count,
                    snapshot.mode,
                    snapshot.recorded_at,
                    json.dumps(snapshot.metadata),
                )
            log.info(
                "portfolio_snapshot_inserted",
                snapshot_id=snapshot.snapshot_id,
                user_id=snapshot.user_id,
                wallet_id=snapshot.wallet_id,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_snapshot_insert_error",
                snapshot_id=snapshot.snapshot_id,
                error=str(exc),
            )
            return False

    async def get_latest_snapshot(
        self,
        tenant_id: str,
        user_id: str,
        wallet_id: str = "",
    ) -> Optional[PortfolioSnapshot]:
        """Return the most recent snapshot for user+wallet, or None."""
        sql = """
            SELECT * FROM portfolio_snapshots
            WHERE tenant_id = $1 AND user_id = $2
              AND ($3 = '' OR wallet_id = $3)
            ORDER BY recorded_at DESC
            LIMIT 1
        """
        try:
            pool = self._db._pool
            if pool is None:
                return None
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql, tenant_id, user_id, wallet_id)
            if row is None:
                return None
            return self._row_to_snapshot(row)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_get_latest_snapshot_error",
                user_id=user_id,
                error=str(exc),
            )
            return None

    async def list_snapshots(
        self,
        tenant_id: str,
        user_id: str,
        wallet_id: str = "",
        limit: int = 30,
    ) -> list[PortfolioSnapshot]:
        """Return recent snapshots for user+wallet, newest first."""
        sql = """
            SELECT * FROM portfolio_snapshots
            WHERE tenant_id = $1 AND user_id = $2
              AND ($3 = '' OR wallet_id = $3)
            ORDER BY recorded_at DESC
            LIMIT $4
        """
        try:
            pool = self._db._pool
            if pool is None:
                return []
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, tenant_id, user_id, wallet_id, limit)
            return [self._row_to_snapshot(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_list_snapshots_error",
                user_id=user_id,
                error=str(exc),
            )
            return []

    # ── Trade reads (realized PnL source) ────────────────────────────────────

    async def get_realized_pnl(
        self,
        user_id: str,
        mode: str = "PAPER",
    ) -> float:
        """Sum realized PnL from closed trades for user+mode."""
        sql = """
            SELECT COALESCE(SUM(pnl), 0.0)
            FROM trades
            WHERE user_id = $1 AND mode = $2 AND status = 'closed'
        """
        try:
            pool = self._db._pool
            if pool is None:
                return 0.0
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql, user_id, mode)
            return float(row[0]) if row else 0.0
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_get_realized_pnl_error",
                user_id=user_id,
                error=str(exc),
            )
            return 0.0

    async def get_open_positions(
        self,
        user_id: str,
    ) -> list[PortfolioPosition]:
        """Return current open paper positions for user."""
        sql = """
            SELECT market_id, side, size, entry_price, current_price,
                   unrealized_pnl, opened_at
            FROM paper_positions
            WHERE status = 'OPEN' AND user_id = $1
        """
        try:
            pool = self._db._pool
            if pool is None:
                return []
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, user_id)
            return [
                PortfolioPosition(
                    market_id=str(r["market_id"]),
                    side=str(r["side"]),
                    size_usd=float(r["size"]),
                    entry_price=float(r["entry_price"]),
                    current_price=float(r["current_price"]),
                    unrealized_pnl=float(r["unrealized_pnl"]),
                    opened_at=float(r["opened_at"]),
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_get_open_positions_error",
                user_id=user_id,
                error=str(exc),
            )
            return []

    async def get_exposure_per_market(
        self,
        user_id: str,
    ) -> dict[str, float]:
        """Return locked USD per open market from paper_positions."""
        sql = """
            SELECT market_id, size
            FROM paper_positions
            WHERE status = 'OPEN' AND user_id = $1
        """
        try:
            pool = self._db._pool
            if pool is None:
                return {}
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, user_id)
            aggregated: dict[str, float] = {}
            for r in rows:
                mid = str(r["market_id"])
                aggregated[mid] = aggregated.get(mid, 0.0) + float(r["size"])
            return aggregated
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_get_exposure_per_market_error",
                user_id=user_id,
                error=str(exc),
            )
            return {}

    # ── Row conversion ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_snapshot(row: Any) -> PortfolioSnapshot:
        metadata: dict[str, Any] = {}
        raw_meta = row["metadata"]
        if isinstance(raw_meta, str):
            try:
                metadata = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        elif isinstance(raw_meta, dict):
            metadata = raw_meta

        recorded_at = row["recorded_at"]
        if isinstance(recorded_at, str):
            recorded_at = datetime.fromisoformat(recorded_at)
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)

        return PortfolioSnapshot(
            snapshot_id=str(row["snapshot_id"]),
            tenant_id=str(row["tenant_id"]),
            user_id=str(row["user_id"]),
            wallet_id=str(row["wallet_id"]),
            realized_pnl=float(row["realized_pnl"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
            net_pnl=float(row["net_pnl"]),
            cash_usd=float(row["cash_usd"]),
            locked_usd=float(row["locked_usd"]),
            equity_usd=float(row["equity_usd"]),
            drawdown=float(row["drawdown"]),
            exposure_pct=float(row["exposure_pct"]),
            position_count=int(row["position_count"]),
            mode=str(row["mode"]),
            recorded_at=recorded_at,
            metadata=metadata,
        )
