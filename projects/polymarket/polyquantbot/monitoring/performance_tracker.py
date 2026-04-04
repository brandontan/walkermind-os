"""Phase 24 — PerformanceTracker: Rolling window of executed trade records.

Maintains a bounded list of the most recent ``max_window`` trades and exposes
simple accessors used by MetricsEngine and ValidationEngine.

Rules:
- Required trade keys are validated on every ``add_trade`` call.
- Trades beyond ``max_window`` are discarded automatically (oldest-first).
- No silent failure — malformed input raises ``ValueError``.
- All mutations are synchronous and safe within a single asyncio event loop.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"pnl", "entry_price", "exit_price", "size", "timestamp", "signal_type"}
)


class PerformanceTracker:
    """Bounded rolling window of executed trade records.

    Attributes:
        trades:     In-order list of trade dicts (oldest → newest).
        max_window: Maximum number of trades to retain (default 100).
    """

    def __init__(self, max_window: int = 100) -> None:
        if max_window < 1:
            raise ValueError(f"max_window must be ≥ 1, got {max_window}")
        self.max_window: int = max_window
        self.trades: list[dict[str, Any]] = []

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_trade(self, trade: dict[str, Any]) -> None:
        """Append a trade record to the rolling window.

        Args:
            trade: Dict containing at minimum the keys ``pnl``,
                   ``entry_price``, ``exit_price``, ``size``,
                   ``timestamp``, and ``signal_type``.

        Raises:
            ValueError: If any required key is missing.
            TypeError:  If ``trade`` is not a dict.
        """
        if not isinstance(trade, dict):
            raise TypeError(f"trade must be a dict, got {type(trade).__name__}")

        missing = _REQUIRED_KEYS - trade.keys()
        if missing:
            raise ValueError(
                f"Trade is missing required keys: {sorted(missing)}"
            )

        self.trades.append(trade)

        # Trim oldest entries beyond the rolling window
        if len(self.trades) > self.max_window:
            excess = len(self.trades) - self.max_window
            self.trades = self.trades[excess:]

        log.debug(
            "performance_tracker_trade_added",
            trade_count=len(self.trades),
            signal_type=trade.get("signal_type"),
            pnl=trade.get("pnl"),
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_recent_trades(self) -> list[dict[str, Any]]:
        """Return a copy of all trades in the current window (oldest → newest)."""
        return list(self.trades)

    def get_trade_count(self) -> int:
        """Return the number of trades currently retained in the window."""
        return len(self.trades)
