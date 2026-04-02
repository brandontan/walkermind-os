"""MultiStrategyMetrics — per-strategy performance tracking.

Tracks signals generated, trades executed, wins/losses, and EV captured for
each registered strategy.  Also maintains a global conflicts counter.

Persistence:
    save_to_redis() / load_from_redis() use RedisClient to persist and restore
    the full metrics state across restarts.

Usage::

    from projects.polymarket.polyquantbot.monitoring.multi_strategy_metrics import (
        MultiStrategyMetrics,
        StrategyMetrics,
    )

    metrics = MultiStrategyMetrics(["ev_momentum", "mean_reversion", "liquidity_edge"])
    metrics.record_signal("ev_momentum")
    metrics.record_trade("ev_momentum", won=True, ev_captured=0.08)

    snapshot = metrics.snapshot()
    await metrics.save_to_redis(redis_client)
    await metrics.load_from_redis(redis_client)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

import structlog

if TYPE_CHECKING:
    from ..infra.redis_client import RedisClient

log = structlog.get_logger(__name__)


# ── Per-strategy dataclass ─────────────────────────────────────────────────────


@dataclass
class StrategyMetrics:
    """Performance metrics for a single strategy.

    Attributes:
        strategy_id: Unique strategy name.
        signals_generated: Cumulative number of signals this strategy produced.
        trades_executed: Cumulative number of trades placed for this strategy.
        wins: Cumulative profitable trades.
        losses: Cumulative unprofitable trades.
        total_ev_captured: Sum of EV captured across all trades.
    """

    strategy_id: str
    signals_generated: int = 0
    trades_executed: int = 0
    wins: int = 0
    losses: int = 0
    total_ev_captured: float = 0.0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        """Fraction of winning trades.  Returns 0.0 when no trades recorded."""
        if self.trades_executed == 0:
            return 0.0
        return self.wins / self.trades_executed

    @property
    def ev_capture_rate(self) -> float:
        """Average EV captured per trade.  Returns 0.0 when no trades recorded."""
        if self.trades_executed == 0:
            return 0.0
        return self.total_ev_captured / self.trades_executed

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON logging / snapshot."""
        return {
            "strategy_id": self.strategy_id,
            "signals_generated": self.signals_generated,
            "trades_executed": self.trades_executed,
            "wins": self.wins,
            "losses": self.losses,
            "total_ev_captured": round(self.total_ev_captured, 6),
            "total_pnl": round(self.total_pnl, 6),
            "win_rate": round(self.win_rate, 4),
            "ev_capture_rate": round(self.ev_capture_rate, 6),
        }


# ── MultiStrategyMetrics ──────────────────────────────────────────────────────


class MultiStrategyMetrics:
    """Aggregate performance tracker for all registered strategies.

    Maintains an independent :class:`StrategyMetrics` instance per strategy
    name plus a global conflicts counter that is incremented via
    :meth:`record_conflict`.

    Args:
        strategy_names: List of strategy identifiers to initialise trackers for.
    """

    def __init__(self, strategy_names: List[str]) -> None:
        if not strategy_names:
            raise ValueError("strategy_names must not be empty")

        self._metrics: Dict[str, StrategyMetrics] = {
            name: StrategyMetrics(strategy_id=name)
            for name in strategy_names
        }
        self._conflicts: int = 0
        # Idempotency: set of trade_ids already processed
        self._seen_trade_ids: Set[str] = set()

        log.info(
            "multi_strategy_metrics_initialized",
            strategies=strategy_names,
        )

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_signal(self, strategy_id: str) -> None:
        """Increment the signal counter for *strategy_id*.

        Args:
            strategy_id: Name of the strategy that produced a signal.

        Raises:
            KeyError: If *strategy_id* was not registered at init time.
        """
        self._get_or_raise(strategy_id).signals_generated += 1
        log.debug(
            "multi_strategy_metrics.signal_recorded",
            strategy=strategy_id,
            total=self._metrics[strategy_id].signals_generated,
        )

    def record_trade(
        self,
        strategy_id: str,
        won: bool,
        ev_captured: float = 0.0,
    ) -> None:
        """Record a completed trade outcome for *strategy_id*.

        Args:
            strategy_id: Strategy whose trade was settled.
            won: True if the trade was profitable.
            ev_captured: Realised EV from this trade (may be 0.0).

        Raises:
            KeyError: If *strategy_id* was not registered at init time.
        """
        m = self._get_or_raise(strategy_id)
        m.trades_executed += 1
        if won:
            m.wins += 1
        else:
            m.losses += 1
        m.total_ev_captured += ev_captured

        log.debug(
            "multi_strategy_metrics.trade_recorded",
            strategy=strategy_id,
            won=won,
            ev_captured=round(ev_captured, 4),
            trades_total=m.trades_executed,
        )

    def record_conflict(self) -> None:
        """Increment the global conflicts counter by one."""
        self._conflicts += 1
        log.debug(
            "multi_strategy_metrics.conflict_recorded",
            total_conflicts=self._conflicts,
        )

    def update_trade_result(self, trade: "TradeResult") -> bool:  # type: ignore[name-defined]
        """Update metrics from a live :class:`TradeResult` with idempotency.

        Idempotency is enforced via ``trade.trade_id``.  Calling this method
        twice with the same ``trade_id`` is safe — the second call is a no-op.

        If ``trade.strategy_id`` is not registered, the call is logged at
        WARNING level and silently ignored (pipeline stability over strict
        failure).

        Args:
            trade: Completed :class:`~execution.trade_result.TradeResult`.

        Returns:
            True if the update was applied, False if it was a duplicate or the
            strategy_id was not registered.
        """
        from execution.trade_result import TradeResult  # local import to avoid cycles

        # ── Idempotency guard ─────────────────────────────────────────────────
        if trade.trade_id in self._seen_trade_ids:
            log.debug(
                "multi_strategy_metrics.duplicate_trade_skipped",
                trade_id=trade.trade_id,
                strategy_id=trade.strategy_id,
            )
            return False

        # ── Strategy guard ────────────────────────────────────────────────────
        if trade.strategy_id not in self._metrics:
            log.warning(
                "multi_strategy_metrics.unknown_strategy_trade_skipped",
                strategy_id=trade.strategy_id,
                trade_id=trade.trade_id,
            )
            return False

        # ── Apply update ──────────────────────────────────────────────────────
        self._seen_trade_ids.add(trade.trade_id)
        m = self._metrics[trade.strategy_id]
        m.trades_executed += 1
        m.total_pnl = round(m.total_pnl + trade.pnl, 6)
        m.total_ev_captured = round(m.total_ev_captured + trade.expected_ev, 6)
        if trade.won:
            m.wins += 1
        else:
            m.losses += 1

        log.info(
            "multi_strategy_metrics.trade_result_applied",
            trade_id=trade.trade_id,
            strategy_id=trade.strategy_id,
            won=trade.won,
            pnl=round(trade.pnl, 4),
            ev=round(trade.expected_ev, 4),
            trades_total=m.trades_executed,
            win_rate=round(m.win_rate, 4),
        )
        return True

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_metrics(self, strategy_id: str) -> StrategyMetrics:
        """Return the :class:`StrategyMetrics` for *strategy_id*.

        Args:
            strategy_id: Strategy name.

        Returns:
            Live :class:`StrategyMetrics` instance (not a copy).

        Raises:
            KeyError: If *strategy_id* was not registered at init time.
        """
        return self._get_or_raise(strategy_id)

    def snapshot(self) -> Dict[str, dict]:
        """Return a dict snapshot of all strategy metrics.

        Returns:
            Mapping of strategy_id → :meth:`StrategyMetrics.to_dict` output.
        """
        return {name: m.to_dict() for name, m in self._metrics.items()}

    # ── Aggregate properties ──────────────────────────────────────────────────

    @property
    def total_signals(self) -> int:
        """Sum of signals_generated across all strategies."""
        return sum(m.signals_generated for m in self._metrics.values())

    @property
    def total_trades(self) -> int:
        """Sum of trades_executed across all strategies."""
        return sum(m.trades_executed for m in self._metrics.values())

    @property
    def total_conflicts(self) -> int:
        """Cumulative number of conflict events recorded."""
        return self._conflicts

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_or_raise(self, strategy_id: str) -> StrategyMetrics:
        """Return the StrategyMetrics for *strategy_id* or raise KeyError."""
        try:
            return self._metrics[strategy_id]
        except KeyError:
            raise KeyError(
                f"Strategy '{strategy_id}' not registered in MultiStrategyMetrics"
            ) from None

    # ── Redis persistence ─────────────────────────────────────────────────────

    async def save_to_redis(self, redis: "RedisClient") -> bool:
        """Persist all strategy metrics and seen trade IDs to Redis.

        Saves each strategy's metrics individually plus the full snapshot and
        the set of processed trade IDs (for idempotency across restarts).

        Args:
            redis: Connected :class:`~infra.redis_client.RedisClient` instance.

        Returns:
            True if all writes succeeded, False if any write failed.
        """
        success = True

        # Save full snapshot
        snapshot = self.snapshot()
        ok = await redis.save_live_snapshot(snapshot)
        if not ok:
            success = False

        # Save each strategy individually
        for strategy_id, m in self._metrics.items():
            ok = await redis.save_strategy_metrics(strategy_id, m.to_dict())
            if not ok:
                success = False

        # Save seen trade IDs for idempotency
        ok = await redis._set_json(
            "polyquantbot:metrics:seen_trade_ids",
            list(self._seen_trade_ids),
        )
        if not ok:
            success = False

        log.info(
            "multi_strategy_metrics.saved_to_redis",
            strategies=list(self._metrics.keys()),
            seen_trade_ids=len(self._seen_trade_ids),
            success=success,
        )
        return success

    async def load_from_redis(self, redis: "RedisClient") -> bool:
        """Restore strategy metrics and seen trade IDs from Redis.

        Loads each registered strategy's metrics if a saved state exists.
        Unknown strategies in Redis are ignored.  Missing keys restore to
        default state (no data lost).

        Args:
            redis: Connected :class:`~infra.redis_client.RedisClient` instance.

        Returns:
            True if at least one strategy was restored, False if nothing found.
        """
        restored_count = 0

        for strategy_id in self._metrics:
            data = await redis.load_strategy_metrics(strategy_id)
            if data is None:
                continue
            m = self._metrics[strategy_id]
            m.signals_generated = int(data.get("signals_generated", 0))
            m.trades_executed = int(data.get("trades_executed", 0))
            m.wins = int(data.get("wins", 0))
            m.losses = int(data.get("losses", 0))
            m.total_ev_captured = float(data.get("total_ev_captured", 0.0))
            m.total_pnl = float(data.get("total_pnl", 0.0))
            restored_count += 1

        # Restore seen trade IDs
        seen_raw = await redis._get_json("polyquantbot:metrics:seen_trade_ids")
        if seen_raw and isinstance(seen_raw, list):
            self._seen_trade_ids = set(seen_raw)

        log.info(
            "multi_strategy_metrics.loaded_from_redis",
            restored_count=restored_count,
            seen_trade_ids=len(self._seen_trade_ids),
        )
        return restored_count > 0

    def __repr__(self) -> str:
        return (
            f"<MultiStrategyMetrics strategies={list(self._metrics.keys())} "
            f"signals={self.total_signals} trades={self.total_trades} "
            f"conflicts={self._conflicts}>"
        )
