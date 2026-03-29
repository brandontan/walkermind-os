"""Bayesian signal model — unchanged from Phase 2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import structlog

log = structlog.get_logger()

ALPHA = 0.05  # Bayesian update strength


@dataclass
class TradingSignal:
    """Output of the signal model for a single market."""

    market_id: str
    question: str
    p_model: float
    p_market: float
    ev: float
    kelly_f: float
    edge_score: float


class BayesianSignalModel:
    """Generates trading signals using Bayesian EV calculation."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Initialise with config."""
        self._min_ev = cfg.get("trading", {}).get("min_ev_threshold", 0.02)

    def _bayesian_update(self, p_market: float) -> float:
        """Apply Bayesian update: pull p_market toward 0.5 by ALPHA."""
        return p_market + ALPHA * (0.5 - p_market)

    def calculate_ev(self, p_model: float, p_market: float) -> tuple[float, float]:
        """Return (ev, kelly_f) for given model and market probabilities."""
        b = (1.0 / p_market) - 1.0  # decimal odds
        q = 1.0 - p_model
        ev = p_model * b - q
        kelly_f = (p_model * b - q) / b if b > 0 else 0.0
        return ev, kelly_f

    def generate_signal(self, market: Any) -> Optional[TradingSignal]:
        """Generate signal for a single market dict/dataclass.

        Returns None if EV is below threshold.
        """
        try:
            if isinstance(market, dict):
                market_id = market["market_id"]
                question = market.get("question", "")
                p_market = float(market["best_ask"])
            else:
                market_id = market.market_id
                question = market.question
                p_market = float(market.best_ask)

            if p_market <= 0 or p_market >= 1:
                return None

            p_model = self._bayesian_update(p_market)
            ev, kelly_f = self.calculate_ev(p_model, p_market)

            if ev < self._min_ev:
                return None

            edge_score = ev * p_model
            return TradingSignal(
                market_id=market_id,
                question=question,
                p_model=p_model,
                p_market=p_market,
                ev=ev,
                kelly_f=kelly_f,
                edge_score=edge_score,
            )
        except Exception as exc:
            log.warning("signal_generation_error", error=str(exc))
            return None

    def generate_all(self, markets: list[Any]) -> list[TradingSignal]:
        """Generate signals for all markets, sorted by edge_score descending."""
        signals = [s for m in markets if (s := self.generate_signal(m)) is not None]
        return sorted(signals, key=lambda s: s.edge_score, reverse=True)
