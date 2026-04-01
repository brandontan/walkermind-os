"""MultiStrategyMetrics — per-strategy performance tracking.

Tracks signals generated, trades executed, wins/losses, and EV captured for
each registered strategy.  Also maintains a global conflicts counter.

Usage::

    from projects.polymarket.polyquantbot.monitoring.multi_strategy_metrics import (
        MultiStrategyMetrics,
        StrategyMetrics,
    )

    metrics = MultiStrategyMetrics(["ev_momentum", "mean_reversion", "liquidity_edge"])
    metrics.record_signal("ev_momentum")
    metrics.record_trade("ev_momentum", won=True, ev_captured=0.08)

    snapshot = metrics.snapshot()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import structlog

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

    def __repr__(self) -> str:
        return (
            f"<MultiStrategyMetrics strategies={list(self._metrics.keys())} "
            f"signals={self.total_signals} trades={self.total_trades} "
            f"conflicts={self._conflicts}>"
        )
