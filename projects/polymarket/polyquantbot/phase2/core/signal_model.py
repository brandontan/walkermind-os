"""
Bayesian signal model — Phase 2.
Now returns ALL valid signals per cycle with edge_score for ranking.
edge_score = ev * p_model  (confidence-weighted EV placeholder for Z-score in R3)
"""

import structlog
from dataclasses import dataclass
from infra.polymarket_client import MarketData

log = structlog.get_logger()

ALPHA = 0.05


@dataclass
class SignalResult:
    market_id: str
    question: str
    outcome: str
    p_model: float
    p_market: float
    ev: float
    edge_score: float   # ranking score: confidence-weighted EV


def calculate_ev(p_model: float, p_market: float) -> float:
    """EV = p * b - (1 - p), where b = (1/p_market) - 1."""
    if p_market <= 0 or p_market >= 1:
        return -999.0
    b = (1.0 / p_market) - 1.0
    return p_model * b - (1.0 - p_model)


class BayesianSignalModel:
    def __init__(self, min_ev_threshold: float) -> None:
        """Initialise with the minimum EV required to generate a signal."""
        self.min_ev_threshold = min_ev_threshold

    def generate_signal(self, market: MarketData) -> SignalResult | None:
        """Evaluate a single market. Returns SignalResult if EV >= threshold."""
        p_market = market.p_market
        p_model = min(p_market + ALPHA, 0.99)
        ev = calculate_ev(p_model, p_market)

        log.debug(
            "signal_evaluated",
            market_id=market.market_id,
            p_market=p_market,
            p_model=p_model,
            ev=round(ev, 6),
        )

        if ev < self.min_ev_threshold:
            return None

        edge_score = ev * p_model

        return SignalResult(
            market_id=market.market_id,
            question=market.question,
            outcome="YES",
            p_model=p_model,
            p_market=p_market,
            ev=ev,
            edge_score=edge_score,
        )

    def generate_all(self, markets: list[MarketData]) -> list[SignalResult]:
        """Return ALL valid signals sorted by edge_score descending."""
        signals: list[SignalResult] = []
        for m in markets:
            try:
                sig = self.generate_signal(m)
                if sig:
                    signals.append(sig)
            except Exception as exc:
                log.warning("signal_generation_error", market_id=m.market_id, error=str(exc))
        signals.sort(key=lambda s: s.edge_score, reverse=True)
        log.info("signals_generated", count=len(signals))
        return signals
