"""
Bayesian signal model.
p_model: derived from market price with a configurable alpha boost
          representing our informational edge hypothesis.
EV = p_model * (1/p_market - 1) - (1 - p_model)
"""

import structlog
from dataclasses import dataclass
from infra.polymarket_client import MarketData

log = structlog.get_logger()

ALPHA = 0.05   # assumed informational edge over market price


@dataclass
class SignalResult:
    market_id: str
    question: str
    outcome: str
    p_model: float
    p_market: float
    ev: float


def calculate_ev(p_model: float, p_market: float) -> float:
    """
    EV = p * b - (1 - p)
    where b = (1 / p_market) - 1  (decimal odds - 1)
    """
    if p_market <= 0 or p_market >= 1:
        return -999.0
    b = (1.0 / p_market) - 1.0
    return p_model * b - (1.0 - p_model)


class BayesianSignalModel:
    def __init__(self, min_ev_threshold: float) -> None:
        """Initialise with the minimum EV required to generate a signal."""
        self.min_ev_threshold = min_ev_threshold

    def generate_signal(self, market: MarketData) -> SignalResult | None:
        """
        Apply Bayesian update: assume our model slightly favours YES.
        Only return signal if EV > threshold.
        """
        p_market = market.p_market
        p_model = min(p_market + ALPHA, 0.99)   # Bayesian posterior

        ev = calculate_ev(p_model, p_market)

        log.debug(
            "signal_evaluated",
            market_id=market.market_id,
            p_market=p_market,
            p_model=p_model,
            ev=ev,
        )

        if ev < self.min_ev_threshold:
            return None

        return SignalResult(
            market_id=market.market_id,
            question=market.question,
            outcome="YES",
            p_model=p_model,
            p_market=p_market,
            ev=ev,
        )

    def select_best(self, signals: list[SignalResult]) -> SignalResult | None:
        """Return the signal with the highest EV, or None if list is empty."""
        if not signals:
            return None
        return max(signals, key=lambda s: s.ev)
