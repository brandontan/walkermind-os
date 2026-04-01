"""Strategy layer — base classes, implementations, router, and allocator."""
from __future__ import annotations

from .allocator import AllocationDecision, StrategyAllocator
from .router import RouterResult, StrategyRouter

__all__ = [
    "StrategyRouter",
    "RouterResult",
    "StrategyAllocator",
    "AllocationDecision",
]
