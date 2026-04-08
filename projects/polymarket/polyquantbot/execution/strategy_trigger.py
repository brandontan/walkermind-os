from __future__ import annotations

from dataclasses import dataclass
import time
import structlog
import uuid

from .engine import ExecutionEngine
from .intelligence import ExecutionIntelligence, MarketSnapshot
from .trade_trace import TradeTraceEngine

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StrategyConfig:
    market_id: str
    side: str = "YES"
    threshold: float = 0.45
    target_pnl: float = 25.0
    social_spike_threshold: float = 0.70
    min_mention_surge_ratio: float = 1.8
    min_author_diversity: int = 15
    min_acceleration: float = 0.5
    min_market_lag: float = 0.03
    min_edge: float = 0.02
    min_liquidity_usd: float = 10_000.0


@dataclass(frozen=True)
class SocialPulseInput:
    mention_surge_ratio: float
    author_diversity: int
    acceleration: float
    narrative_probability: float
    liquidity_usd: float
    risk_constraints_ok: bool = True


@dataclass(frozen=True)
class StrategyDecision:
    decision: str
    reason: str
    edge: float


class StrategyTrigger:
    """Strategy trigger with execution intelligence.
    
    IF price < threshold AND entry_score >= 0.5 -> open position
    IF pnl > target -> close position
    """

    def __init__(self, engine: ExecutionEngine, config: StrategyConfig) -> None:
        self._engine = engine
        self._config = config
        self._intelligence = ExecutionIntelligence()
        self._last_trigger_time: float | None = None
        self._cooldown_seconds = 30.0  # Anti-loop guard
        self._trace_engine = TradeTraceEngine()

    def evaluate_breaking_news_momentum(
        self,
        market_price: float,
        social_pulse: SocialPulseInput,
    ) -> StrategyDecision:
        mention_score = min(
            1.0,
            social_pulse.mention_surge_ratio / max(self._config.min_mention_surge_ratio, 1e-6),
        )
        author_score = min(
            1.0,
            social_pulse.author_diversity / max(float(self._config.min_author_diversity), 1.0),
        )
        acceleration_score = min(
            1.0,
            social_pulse.acceleration / max(self._config.min_acceleration, 1e-6),
        )

        spike_score = (0.5 * mention_score) + (0.3 * author_score) + (0.2 * acceleration_score)
        if spike_score < self._config.social_spike_threshold:
            return StrategyDecision(
                decision="SKIP",
                reason="weak signal: social spike below threshold",
                edge=0.0,
            )

        narrative_prob = min(max(social_pulse.narrative_probability, 0.01), 0.99)
        market_prob = min(max(market_price, 0.01), 0.99)
        price_lag = abs(narrative_prob - market_prob)

        if price_lag < self._config.min_market_lag:
            return StrategyDecision(
                decision="SKIP",
                reason="already priced in: market lag too small",
                edge=0.0,
            )

        implied_odds = (1.0 - market_prob) / market_prob
        edge = max(0.0, (narrative_prob * implied_odds) - (1.0 - narrative_prob))

        if edge <= self._config.min_edge:
            return StrategyDecision(
                decision="SKIP",
                reason="weak signal: edge below threshold",
                edge=round(edge, 6),
            )

        if social_pulse.liquidity_usd < self._config.min_liquidity_usd:
            return StrategyDecision(
                decision="SKIP",
                reason="low liquidity: below minimum depth requirement",
                edge=round(edge, 6),
            )

        if not social_pulse.risk_constraints_ok:
            return StrategyDecision(
                decision="SKIP",
                reason="risk constraints blocked entry",
                edge=round(edge, 6),
            )

        return StrategyDecision(
            decision="ENTER",
            reason="entry conditions met: social spike + market lag + edge",
            edge=round(edge, 6),
        )

    async def evaluate(self, market_price: float) -> str:
        now = time.time()
        if self._last_trigger_time and (now - self._last_trigger_time) < self._cooldown_seconds:
            return "COOLDOWN"
        self._last_trigger_time = now

        snapshot = await self._engine.snapshot()
        open_pos = next((p for p in snapshot.positions if p.market_id == self._config.market_id), None)

        market_snapshot = MarketSnapshot(
            price=market_price,
            implied_prob=snapshot.implied_prob,
            volatility=snapshot.volatility
        )
        entry_eval = self._intelligence.evaluate_entry(market_snapshot)
        entry_score = float(entry_eval.get("score", 0.0))
        entry_reasons = entry_eval.get("reasons", [])

        log.info(
            "intelligence_decision",
            score=entry_score,
            threshold=0.5,
            decision="EXECUTE" if entry_score >= 0.5 else "HOLD"
        )

        if open_pos is None and market_price < self._config.threshold and entry_score >= 0.5:
            size = snapshot.equity * self._engine.max_position_size_ratio
            created = await self._engine.open_position(
                market=self._config.market_id,
                side=self._config.side,
                price=market_price,
                size=size,
                position_id=str(uuid.uuid4()),
            )
            if created:
                self._trace_engine.record_trace(
                    position_id=created.position_id,
                    market_id=self._config.market_id,
                    entry_price=market_price,
                    exit_price=0.0,
                    size=size,
                    pnl=0.0,
                    intelligence_score=entry_score,
                    intelligence_reasons=entry_reasons,
                    decision_threshold=0.5,
                    action="OPEN",
                )
            return "OPENED" if created is not None else "BLOCKED"

        if open_pos is not None:
            await self._engine.update_mark_to_market({self._config.market_id: market_price})
            refreshed = await self._engine.snapshot()
            tracked = next((p for p in refreshed.positions if p.market_id == self._config.market_id), None)
            if tracked is not None and tracked.pnl > self._config.target_pnl:
                await self._engine.close_position(tracked, market_price)
                self._trace_engine.record_trace(
                    position_id=tracked.position_id,
                    market_id=self._config.market_id,
                    entry_price=tracked.entry_price,
                    exit_price=market_price,
                    size=tracked.size,
                    pnl=tracked.pnl,
                    intelligence_score=entry_score,
                    intelligence_reasons=entry_reasons,
                    decision_threshold=0.5,
                    action="CLOSE",
                )
                return "CLOSED"

        return "HOLD"
