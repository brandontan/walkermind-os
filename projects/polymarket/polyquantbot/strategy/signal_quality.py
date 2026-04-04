"""Phase 24 — SignalQualityAnalyzer: REAL vs SYNTHETIC performance comparison.

Separates the trade list into REAL-signal trades and SYNTHETIC-signal trades,
computes per-group win rates and total PnL, then flags degradation when
synthetic signals materially outperform real ones.

Degradation threshold (drift warning):
    If synthetic_wr > real_wr + DRIFT_THRESHOLD (default 0.20),
    a WARNING is logged.

The method is intentionally stateless — pass any slice of trades and receive
a fresh analysis dict.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

# Minimum advantage of synthetic WR over real WR to flag a drift warning
_DRIFT_THRESHOLD: float = 0.20

_REAL = "REAL"
_SYNTHETIC = "SYNTHETIC"


class SignalQualityAnalyzer:
    """Compare REAL and SYNTHETIC signal performance.

    Usage::

        analyzer = SignalQualityAnalyzer()
        result = analyzer.evaluate(trades)
    """

    def evaluate(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute per-signal-type metrics and detect performance drift.

        Args:
            trades: List of trade dicts.  Each must contain at minimum the
                    keys ``pnl`` (float) and ``signal_type`` (``"REAL"`` or
                    ``"SYNTHETIC"``).

        Returns:
            Dict with keys:
                ``real_wr``       — Win rate for REAL trades (float, 0.0 if none).
                ``synthetic_wr``  — Win rate for SYNTHETIC trades (float, 0.0 if none).
                ``real_pnl``      — Total PnL for REAL trades.
                ``synthetic_pnl`` — Total PnL for SYNTHETIC trades.
                ``drift_warning`` — True when synthetic >> real by more than
                                    the drift threshold.
        """
        real_trades = [
            t for t in trades if t.get("signal_type") == _REAL
        ]
        synthetic_trades = [
            t for t in trades if t.get("signal_type") == _SYNTHETIC
        ]

        real_wr = self._win_rate(real_trades)
        synthetic_wr = self._win_rate(synthetic_trades)
        real_pnl = sum(t.get("pnl", 0.0) for t in real_trades)
        synthetic_pnl = sum(t.get("pnl", 0.0) for t in synthetic_trades)

        drift_warning = (synthetic_wr - real_wr) > _DRIFT_THRESHOLD

        result: dict[str, Any] = {
            "real_wr": real_wr,
            "synthetic_wr": synthetic_wr,
            "real_pnl": real_pnl,
            "synthetic_pnl": synthetic_pnl,
            "drift_warning": drift_warning,
        }

        if drift_warning:
            log.warning(
                "signal_quality_drift_detected",
                real_wr=round(real_wr, 4),
                synthetic_wr=round(synthetic_wr, 4),
                delta=round(synthetic_wr - real_wr, 4),
                threshold=_DRIFT_THRESHOLD,
            )
        else:
            log.debug(
                "signal_quality_evaluated",
                real_wr=round(real_wr, 4),
                synthetic_wr=round(synthetic_wr, 4),
                real_pnl=round(real_pnl, 4),
                synthetic_pnl=round(synthetic_pnl, 4),
            )

        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _win_rate(trades: list[dict[str, Any]]) -> float:
        """Return fraction of trades with pnl > 0; 0.0 for empty list."""
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get("pnl", 0.0) > 0.0)
        return wins / len(trades)
