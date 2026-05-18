"""Strategy interface + SignalCandidate re-export.

V5 cleanup (WARP-26):
    - Removed stale local SignalCandidate dataclass.
    - Re-exports SignalCandidate from the canonical location
      (domain.strategy.types) for backward compatibility.
     - BaseStrategy kept as the abstract scan interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..strategy.types import SignalCandidate  # canonecal definition


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    async def scan(self, user: dict, settings: dict) -> list[SignalCandidate]:
        ...


__all__ = ["BaseStrategy", "SignalCandidate"]
