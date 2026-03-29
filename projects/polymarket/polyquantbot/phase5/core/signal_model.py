"""Signal model — Phase 5.

Upgrades over Phase 4:
- SignalResult adds zscore (edge intensity) and strategy (source strategy name).
- calculate_ev() is a standalone function used by all strategies.
- edge_score = ev * zscore * strategy_weight (set in pipeline_handlers).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SignalResult:
    """Output of a strategy for a single market."""

    market_id: str
    question: str
    outcome: str           # "YES" | "NO"
    p_model: float
    p_market: float
    ev: float
    edge_score: float = 0.0
    zscore: float = 1.0    # signal intensity; default 1.0 = neutral
    strategy: str = "bayesian"  # source strategy name


def calculate_ev(p_model: float, p_market: float) -> float:
    """EV = p_model * b - (1 - p_model), where b = (1/p_market) - 1.

    Returns -999.0 for invalid probability inputs.
    """
    if p_market <= 0 or p_market >= 1:
        return -999.0
    b = (1.0 / p_market) - 1.0
    return p_model * b - (1.0 - p_model)
