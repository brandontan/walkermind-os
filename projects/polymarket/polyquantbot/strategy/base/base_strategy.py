"""Base strategy interface for all polyquantbot trading strategies."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import structlog

log = structlog.get_logger(__name__)


@dataclass
class SignalResult:
    """Result returned from a strategy's evaluate() method."""

    market_id: str
    side: str  # "YES" or "NO"
    edge: float  # expected value edge, e.g. 0.05 = 5%
    size_usdc: float  # recommended position size in USDC
    confidence: float = 1.0  # 0.0–1.0 confidence multiplier
    metadata: Dict[str, Any] = field(default_factory=dict)


# Alias for forward compatibility with pipeline references
Signal = SignalResult


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Subclasses must implement:
    - name (property)
    - evaluate() → Optional[SignalResult]
    """

    def __init__(self, min_edge: float = 0.02) -> None:
        self._min_edge = min_edge
        self._lock = asyncio.Lock()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier."""
        ...

    @abstractmethod
    async def evaluate(
        self,
        market_id: str,
        market_data: Dict[str, Any],
    ) -> Optional[SignalResult]:
        """
        Evaluate a market and return a signal or None.

        Args:
            market_id: Polymarket market identifier.
            market_data: Current market state (orderbook, price, etc.).

        Returns:
            SignalResult if signal passes min_edge, else None.
        """
        ...

    async def is_ready(self) -> bool:
        """Return True if strategy has sufficient data to evaluate."""
        return True

    def __repr__(self) -> str:
        return f"<Strategy name={self.name} min_edge={self._min_edge}>"
