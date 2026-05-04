"""Strategy interface + SignalCandidate dataclass."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class SignalCandidate:
    market_id: str
    side: str                # "yes" | "no"
    size_usdc: Decimal
    price: float
    edge_bps: Optional[float] = None
    strategy_type: str = "copy_trade"
    signal_ts: Optional[datetime] = None
    extra: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    async def scan(self, user: dict, settings: dict) -> list[SignalCandidate]:
        ...
