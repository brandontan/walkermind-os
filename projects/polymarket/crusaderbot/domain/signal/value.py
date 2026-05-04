"""Value strategy stub — Phase R6b+. Returns no signals until model validated."""
from __future__ import annotations

from .base import BaseStrategy, SignalCandidate


class ValueStrategy(BaseStrategy):
    name = "value"

    async def scan(self, user: dict, settings: dict) -> list[SignalCandidate]:
        return []
