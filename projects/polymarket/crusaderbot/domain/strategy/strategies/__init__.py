"""Built-in CrusaderBot strategy implementations.

Each module in this package exports exactly one concrete `BaseStrategy`
subclass. The registry bootstrap (`StrategyRegistry.bootstrap_default_strategies`)
imports them here and registers a fresh instance per process.

WARP/R00T/strategy-system-cleanup narrowed this set to the 3 strategies with
a real user-facing trigger path. ConfluenceScalperStrategy and
MomentumReversalStrategy were archived — neither had a visible preset that
routed to it, so the toggles were cosmetic.
"""

from .copy_trade import CopyTradeStrategy
from .late_entry_v3 import LateEntryV3Strategy
from .signal_following import SignalFollowingStrategy

__all__ = [
    "CopyTradeStrategy",
    "LateEntryV3Strategy",
    "SignalFollowingStrategy",
]
