# projects/polymarket/polyquantbot/platform/gateway/__init__.py
# NEXUS/FORGE-X — Phase 2.8: Enforce adapter usage in gateway

from .legacy_core_adapter import (
    LegacyCoreFacadeAdapter,
    ExecutionSignal,
    TradeValidation,
    ExecutionContext,
)

# --- Core Access Guard ---
# All core interactions MUST go through LegacyCoreFacadeAdapter.
# Direct imports of core.* are forbidden in this module.

__all__ = [
    "LegacyCoreFacadeAdapter",
    "ExecutionSignal",
    "TradeValidation",
    "ExecutionContext",
]