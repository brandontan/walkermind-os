"""Built-in CrusaderBot strategy implementations.

Each module in this package exports exactly one concrete `BaseStrategy`
subclass. The registry bootstrap (`StrategyRegistry.bootstrap_default_strategies`)
imports them here and registers a fresh instance per process.
"""

from .copy_trade import CopyTradeStrategy

__all__ = ["CopyTradeStrategy"]
