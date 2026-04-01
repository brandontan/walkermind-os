"""Strategy implementations — concrete trading strategies for PolyQuantBot.

Available strategies:
  - EVMomentumStrategy   : trades when model-probability momentum diverges from market price
  - MeanReversionStrategy: trades when price deviates from its EWMA baseline
  - LiquidityEdgeStrategy: trades spread dislocations on the deeper side of the book

All strategies extend BaseStrategy and return Optional[SignalResult].

Usage::

    from projects.polymarket.polyquantbot.strategy.implementations import (
        EVMomentumStrategy,
        MeanReversionStrategy,
        LiquidityEdgeStrategy,
        STRATEGY_REGISTRY,
    )

    strategy = STRATEGY_REGISTRY["ev_momentum"]()
    signal = await strategy.evaluate(market_id, market_data)
"""
from __future__ import annotations

from .ev_momentum import EVMomentumStrategy
from .liquidity_edge import LiquidityEdgeStrategy
from .mean_reversion import MeanReversionStrategy

# Registry maps strategy name → class for dynamic instantiation.
# Keys match the ``name`` property of each strategy instance.
STRATEGY_REGISTRY: dict[str, type] = {
    "ev_momentum": EVMomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "liquidity_edge": LiquidityEdgeStrategy,
}

__all__ = [
    "EVMomentumStrategy",
    "MeanReversionStrategy",
    "LiquidityEdgeStrategy",
    "STRATEGY_REGISTRY",
]
