"""Strategy manager — Phase 6. Unchanged from Phase 5.

Tracks per-strategy performance and controls enable/disable/weighting.
score = 0.4 * winrate + 0.6 * clamp(ev_ratio, 0, 2)
Auto-disables if score < disable_threshold after min_trades.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()


def _clamp(v: float, lo: float, hi: float) -> float:
    """Clamp value between lo and hi."""
    return max(lo, min(hi, v))


@dataclass
class StrategyStats:
    """Per-strategy rolling performance counters."""

    name: str
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0
    ev_sum: float = 0.0
    peak_pnl: float = 0.0
    trough_pnl: float = 0.0


class StrategyManager:
    """Controls strategy lifecycle based on live performance scoring."""

    def __init__(self, disable_threshold: float, min_trades: int) -> None:
        """Initialise with auto-disable threshold and minimum trades required."""
        self._disable_threshold = disable_threshold
        self._min_trades = min_trades
        self._stats: dict[str, StrategyStats] = {}

    def _get(self, name: str) -> StrategyStats:
        """Return or create stats entry for strategy."""
        if name not in self._stats:
            self._stats[name] = StrategyStats(name=name)
        return self._stats[name]

    def record_trade(self, strategy: str, pnl: float, ev: float) -> None:
        """Update stats after a trade closes."""
        st = self._get(strategy)
        st.trades += 1
        st.pnl += pnl
        st.ev_sum += ev
        if pnl > 0:
            st.wins += 1
        if st.pnl > st.peak_pnl:
            st.peak_pnl = st.pnl
        if st.pnl < st.trough_pnl:
            st.trough_pnl = st.pnl
        log.info(
            "strategy_update",
            name=strategy,
            score=round(self.get_score(strategy), 4),
            winrate=round(st.wins / max(st.trades, 1), 4),
            pnl=round(st.pnl, 2),
            trades=st.trades,
            enabled=self.is_enabled(strategy),
        )

    def get_score(self, name: str) -> float:
        """Compute score = 0.4 * winrate + 0.6 * clamp(ev_ratio, 0, 2)."""
        st = self._get(name)
        winrate = st.wins / max(st.trades, 1)
        ev_ratio = st.pnl / max(st.ev_sum, 1e-9)
        return 0.4 * winrate + 0.6 * _clamp(ev_ratio, 0.0, 2.0)

    def is_enabled(self, name: str) -> bool:
        """Return False only when min_trades met AND score < disable_threshold."""
        st = self._get(name)
        if st.trades >= self._min_trades and self.get_score(name) < self._disable_threshold:
            log.warning("strategy_disabled", name=name,
                        score=round(self.get_score(name), 4))
            return False
        return True

    def weight(self, name: str) -> float:
        """Return strategy weight for edge_score scaling. Minimum 0.1."""
        return max(self.get_score(name), 0.1)

    def all_stats(self) -> list[dict]:
        """Return current stats for all tracked strategies."""
        return [
            {
                "name": st.name,
                "trades": st.trades,
                "wins": st.wins,
                "pnl": round(st.pnl, 2),
                "score": round(self.get_score(st.name), 4),
                "enabled": self.is_enabled(st.name),
            }
            for st in self._stats.values()
        ]
