from dataclasses import dataclass
import math
import time

@dataclass
class MarketSnapshot:
    price: float
    implied_prob: float
    volatility: float

class ExecutionIntelligence:
    def evaluate_entry(self, market: MarketSnapshot) -> float:
        """Score entry opportunity (0–1)."""
        price_edge = 1 - abs(market.price - market.implied_prob)
        volatility_penalty = 1 / (1 + math.log(market.volatility + 1))
        return min(1.0, max(0.0, price_edge * volatility_penalty))

    def evaluate_exit(self, position) -> str:
        """Signal exit action."""
        if position.pnl > 0.15 * position.size:  # 15% profit
            return "TAKE_PROFIT"
        if position.pnl < -0.05 * position.size:  # 5% loss
            return "CUT_LOSS"
        return "HOLD"