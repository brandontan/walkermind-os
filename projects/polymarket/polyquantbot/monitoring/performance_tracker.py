"""Phase 24 — PerformanceTracker: Rolling window of executed trade records.

Maintains a bounded list of the most recent ``max_window`` trades and exposes
simple accessors used by MetricsEngine and ValidationEngine.

Rules:
- Required trade keys are validated on every ``add_trade`` call.
- Trades beyond ``max_window`` are discarded automatically (oldest-first).
- No silent failure — malformed input raises ``ValueError``.
- All mutations are synchronous and safe within a single asyncio event loop.
- ``trade_id`` (optional key in trade dict) enables in-place PnL updates via
  ``update_trade(trade_id, pnl)`` to reflect closed-trade realized PnL.
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
        # trade_id → index in self.trades (invalidated when window trims)
        self._trade_id_index: dict[str, int] = {}

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_trade(self, trade: dict[str, Any]) -> None:
        """Append a trade record to the rolling window.

        If the trade dict contains a ``trade_id`` key its value is stored in
        the internal index so that ``update_trade`` can locate and overwrite
        the entry when the position is later closed.

        Args:
            trade: Dict containing at minimum the keys ``pnl``,
                   ``entry_price``, ``exit_price``, ``size``,
                   ``timestamp``, and ``signal_type``.  An optional
                   ``trade_id`` key enables later PnL updates.

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

        # Record trade_id → index before appending (index = current length)
        _tid: str | None = trade.get("trade_id")
        if _tid:
            self._trade_id_index[_tid] = len(self.trades)

        self.trades.append(trade)

        # Trim oldest entries beyond the rolling window
        if len(self.trades) > self.max_window:
            excess = len(self.trades) - self.max_window
            # Invalidate indices for removed entries
            removed_ids = [tid for tid, idx in self._trade_id_index.items() if idx < excess]
            for tid in removed_ids:
                del self._trade_id_index[tid]
            # Shift remaining indices
            self._trade_id_index = {
                tid: idx - excess
                for tid, idx in self._trade_id_index.items()
            }
            self.trades = self.trades[excess:]

        log.debug(
            "performance_tracker_trade_added",
            trade_count=len(self.trades),
            signal_type=trade.get("signal_type"),
            pnl=trade.get("pnl"),
            trade_id=_tid,
        )

    def update_trade(self, trade_id: str, pnl: float) -> bool:
        """Overwrite the ``pnl`` field of an existing trade by its ``trade_id``.

        Used to reflect realized (closed-trade) PnL after a position is closed,
        replacing the placeholder ``0.0`` recorded at trade open.

        Duplicate calls with the same ``trade_id`` are silently ignored after
        the first successful update (the trade remains in the window with the
        previously written PnL value).

        Args:
            trade_id: Identifier previously supplied via the ``trade_id`` key
                      of ``add_trade``.
            pnl:      Realized PnL to write (positive = profit).

        Returns:
            ``True`` if the trade was found and updated, ``False`` if the
            ``trade_id`` is not present in the current window (e.g. it was
            already trimmed).
        """
        idx = self._trade_id_index.get(trade_id)
        if idx is None:
            log.warning(
                "performance_tracker_update_trade_not_found",
                trade_id=trade_id,
                hint="trade_id not in current window — may have been trimmed",
            )
            return False

        self.trades[idx] = {**self.trades[idx], "pnl": pnl}
        log.debug(
            "performance_tracker_trade_updated",
            trade_id=trade_id,
            pnl=pnl,
            index=idx,
        )
        return True

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_recent_trades(self) -> list[dict[str, Any]]:
        """Return a copy of all trades in the current window (oldest → newest)."""
        return list(self.trades)

    def get_trade_count(self) -> int:
        """Return the number of trades currently retained in the window."""
        return len(self.trades)
