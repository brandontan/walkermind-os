from dataclasses import dataclass
import math


@dataclass
class MarketSnapshot:
    price: float
    implied_prob: float
    volatility: float


class ExecutionIntelligence:
    def evaluate_entry(self, market: MarketSnapshot, threshold: float = 0.5) -> dict:
        """Score entry opportunity (0–1) with reasons."""
        price_edge = 1 - abs(market.price - market.implied_prob)
        volatility_penalty = 1 / (1 + math.log(market.volatility + 1))
        score = min(1.0, max(0.0, price_edge * volatility_penalty))
        reasons = []
        if price_edge > 0.1:
            reasons.append("price deviation")
        if market.volatility < 0.5:
            reasons.append("low volatility")
        return {"score": score, "reasons": reasons}

    def should_open(self, score: float, threshold: float) -> bool:
        """Strictly enforce threshold."""
        return score >= threshold

    def evaluate_exit(self, position) -> str:
        """Signal exit action."""
        if position.pnl > 0.15 * position.size:
            return "TAKE_PROFIT"
        if position.pnl < -0.05 * position.size:
            return "CUT_LOSS"
        return "HOLD"