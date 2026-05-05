"""CrusaderBot strategy plane — pluggable strategy interface and registry.

Public surface (foundation-only):
    BaseStrategy        — ABC every concrete strategy must implement
    StrategyRegistry    — process-wide singleton catalog
    SignalCandidate     — strategy output, consumed by risk gate downstream
    ExitDecision        — per-position strategy exit evaluation result
    MarketFilters       — user filter envelope passed to scan()
    UserContext         — per-user context envelope passed to scan()
"""

from .base import BaseStrategy
from .registry import StrategyRegistry, bootstrap_default_strategies
from .types import (
    ExitDecision,
    MarketFilters,
    SignalCandidate,
    UserContext,
)

__all__ = [
    "BaseStrategy",
    "StrategyRegistry",
    "bootstrap_default_strategies",
    "SignalCandidate",
    "ExitDecision",
    "MarketFilters",
    "UserContext",
]
