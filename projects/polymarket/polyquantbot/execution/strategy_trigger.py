from __future__ import annotations

from dataclasses import dataclass

from .engine import ExecutionEngine


@dataclass(frozen=True)
class StrategyConfig:
    market_id: str
    side: str = "YES"
    threshold: float = 0.45
    target_pnl: float = 25.0


class StrategyTrigger:
    """Simple paper strategy trigger.

    IF price < threshold -> open position
    IF pnl > target -> close position
    """

    def __init__(self, engine: ExecutionEngine, config: StrategyConfig) -> None:
        self._engine = engine
        self._config = config

    async def evaluate(self, market_price: float) -> str:
        snapshot = await self._engine.snapshot()
        open_pos = next((p for p in snapshot.positions if p.market_id == self._config.market_id), None)

        if open_pos is None and market_price < self._config.threshold:
            size = snapshot.equity * self._engine.max_position_size_ratio
            created = await self._engine.open_position(
                market=self._config.market_id,
                side=self._config.side,
                price=market_price,
                size=size,
            )
            return "OPENED" if created is not None else "BLOCKED"

        if open_pos is not None:
            await self._engine.update_mark_to_market({self._config.market_id: market_price})
            refreshed = await self._engine.snapshot()
            tracked = next((p for p in refreshed.positions if p.market_id == self._config.market_id), None)
            if tracked is not None and tracked.pnl > self._config.target_pnl:
                await self._engine.close_position(tracked, market_price)
                return "CLOSED"

        return "HOLD"
