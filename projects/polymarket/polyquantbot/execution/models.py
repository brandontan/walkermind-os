from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    """Paper trading position state for execution engine."""

    market_id: str
    side: str
    entry_price: float
    current_price: float
    size: float
    pnl: float = 0.0

    def exposure(self) -> float:
        return self.size

    def update_price(self, price: float) -> float:
        self.current_price = float(price)
        direction = 1.0 if self.side.upper() == "YES" else -1.0
        self.pnl = (self.current_price - self.entry_price) * self.size * direction
        return self.pnl
