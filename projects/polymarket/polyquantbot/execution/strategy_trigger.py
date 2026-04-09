from __future__ import annotations

from dataclasses import dataclass
import time
import structlog
import uuid
import re

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
    cross_exchange_min_net_edge: float = 0.02
    cross_exchange_min_actionable_spread: float = 0.005
    cross_exchange_min_mapping_confidence: float = 0.55
    cross_exchange_min_overlap_tokens: int = 2
    min_position_size_usd: float = 25.0
    max_position_size_ratio: float = 0.10


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


@dataclass(frozen=True)
class CrossExchangeMarket:
    exchange: str
    market_id: str
    title: str
    probability: float
    liquidity_usd: float
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    timeframe: str = ""
    resolution_criteria: str = ""
    event_key: str = ""


@dataclass(frozen=True)
class CrossExchangeArbitrageDecision:
    decision: str
    reason: str
    edge: float
    matched_markets_info: dict[str, object]


@dataclass(frozen=True)
class WalletTradeSignal:
    wallet_address: str
    action: str
    size_usd: float
    liquidity_usd: float
    timestamp_ms: int
    market_move_pct: float
    wallet_success_rate: float
    wallet_activity_count: int


@dataclass(frozen=True)
class SmartMoneyCopyTradingDecision:
    decision: str
    reason: str
    confidence: float
    wallet_info: dict[str, object]


@dataclass(frozen=True)
class StrategyCandidateScore:
    strategy_name: str
    decision: str
    reason: str
    edge: float
    confidence: float
    score: float
    market_metadata: dict[str, object]


@dataclass(frozen=True)
class StrategyAggregationDecision:
    selected_trade: str | None
    ranked_candidates: list[StrategyCandidateScore]
    selection_reason: str
    top_score: float
    decision: str


@dataclass(frozen=True)
class PositionSizingDecision:
    position_size: float
    size_reason: str
    applied_constraints: tuple[str, ...]
    normalized_score: float


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

    def evaluate_cross_exchange_arbitrage(
        self,
        polymarket: CrossExchangeMarket,
        kalshi_markets: list[CrossExchangeMarket],
    ) -> CrossExchangeArbitrageDecision:
        best_match, confidence = self._select_best_cross_exchange_match(
            polymarket=polymarket,
            kalshi_markets=kalshi_markets,
        )
        if best_match is None:
            return CrossExchangeArbitrageDecision(
                decision="SKIP",
                reason="no equivalent market match found",
                edge=0.0,
                matched_markets_info={"polymarket": polymarket.market_id, "match": None},
            )

        if confidence < self._config.cross_exchange_min_mapping_confidence:
            return CrossExchangeArbitrageDecision(
                decision="SKIP",
                reason="mapping confidence too low",
                edge=0.0,
                matched_markets_info={
                    "polymarket": polymarket.market_id,
                    "kalshi": best_match.market_id,
                    "mapping_confidence": round(confidence, 6),
                },
            )

        poly_prob = self._normalize_probability(polymarket.probability)
        kalshi_prob = self._normalize_probability(best_match.probability)
        raw_edge = abs(poly_prob - kalshi_prob)
        if raw_edge < self._config.cross_exchange_min_actionable_spread:
            return CrossExchangeArbitrageDecision(
                decision="SKIP",
                reason="spread not actionable",
                edge=0.0,
                matched_markets_info={
                    "polymarket": polymarket.market_id,
                    "kalshi": best_match.market_id,
                    "mapping_confidence": round(confidence, 6),
                    "raw_edge": round(raw_edge, 6),
                    "net_edge": 0.0,
                },
            )

        fees_slippage = (
            self._bps_to_probability(polymarket.fee_bps + polymarket.slippage_bps)
            + self._bps_to_probability(best_match.fee_bps + best_match.slippage_bps)
        )
        net_edge = max(0.0, raw_edge - fees_slippage)

        if polymarket.liquidity_usd < self._config.min_liquidity_usd or best_match.liquidity_usd < self._config.min_liquidity_usd:
            return CrossExchangeArbitrageDecision(
                decision="SKIP",
                reason="liquidity insufficient for actionable arbitrage",
                edge=round(net_edge, 6),
                matched_markets_info={
                    "polymarket": polymarket.market_id,
                    "kalshi": best_match.market_id,
                    "mapping_confidence": round(confidence, 6),
                    "raw_edge": round(raw_edge, 6),
                    "net_edge": round(net_edge, 6),
                },
            )

        if net_edge <= self._config.cross_exchange_min_net_edge:
            return CrossExchangeArbitrageDecision(
                decision="SKIP",
                reason="fees/slippage adjusted edge below threshold",
                edge=round(net_edge, 6),
                matched_markets_info={
                    "polymarket": polymarket.market_id,
                    "kalshi": best_match.market_id,
                    "mapping_confidence": round(confidence, 6),
                    "raw_edge": round(raw_edge, 6),
                    "net_edge": round(net_edge, 6),
                },
            )

        return CrossExchangeArbitrageDecision(
            decision="ENTER",
            reason="cross-exchange arbitrage opportunity detected",
            edge=round(net_edge, 6),
            matched_markets_info={
                "polymarket": polymarket.market_id,
                "kalshi": best_match.market_id,
                "mapping_confidence": round(confidence, 6),
                "probability_polymarket": round(poly_prob, 6),
                "probability_kalshi": round(kalshi_prob, 6),
                "raw_edge": round(raw_edge, 6),
                "net_edge": round(net_edge, 6),
            },
        )

    def evaluate_smart_money_copy_trading(
        self,
        signal: WalletTradeSignal,
        related_wallet_signals: list[WalletTradeSignal],
    ) -> SmartMoneyCopyTradingDecision:
        min_success_rate = 0.60
        min_activity_count = 15
        large_position_usd = 10_000.0
        early_entry_max_move_pct = 0.02
        repeated_wallet_min_count = 2
        min_confidence_threshold = 0.65

        if signal.wallet_success_rate < min_success_rate or signal.wallet_activity_count < min_activity_count:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="low-quality wallet",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "success_rate": round(signal.wallet_success_rate, 4),
                    "activity_count": signal.wallet_activity_count,
                },
            )

        if signal.market_move_pct > early_entry_max_move_pct:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="late entry",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "market_move_pct": round(signal.market_move_pct, 6),
                },
            )

        if signal.action.lower() not in {"buy", "sell"}:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="conflicting signals",
                confidence=0.0,
                wallet_info={"wallet_address": signal.wallet_address},
            )

        same_market_signals = [
            item
            for item in related_wallet_signals
            if item.timestamp_ms >= signal.timestamp_ms - (30 * 60 * 1000)
        ]

        buy_votes = sum(1 for item in same_market_signals if item.action.lower() == "buy")
        sell_votes = sum(1 for item in same_market_signals if item.action.lower() == "sell")
        if buy_votes > 0 and sell_votes > 0:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="conflicting signals",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "buy_votes": buy_votes,
                    "sell_votes": sell_votes,
                },
            )

        if signal.liquidity_usd < self._config.min_liquidity_usd:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="insufficient liquidity",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "liquidity_usd": round(signal.liquidity_usd, 2),
                },
            )

        size_score = min(1.0, signal.size_usd / large_position_usd)
        early_score = max(0.0, 1.0 - (signal.market_move_pct / early_entry_max_move_pct))
        aligned_wallets = sum(1 for item in same_market_signals if item.action.lower() == signal.action.lower())
        repeated_score = min(1.0, aligned_wallets / max(float(repeated_wallet_min_count), 1.0))
        confidence = round((0.4 * size_score) + (0.3 * early_score) + (0.3 * repeated_score), 6)

        if confidence <= min_confidence_threshold:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="signal strength below threshold",
                confidence=confidence,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "aligned_wallets": aligned_wallets,
                },
            )

        return SmartMoneyCopyTradingDecision(
            decision="ENTER",
            reason="high-quality early smart-money signal",
            confidence=confidence,
            wallet_info={
                "wallet_address": signal.wallet_address,
                "action": signal.action.upper(),
                "success_rate": round(signal.wallet_success_rate, 4),
                "activity_count": signal.wallet_activity_count,
                "size_usd": round(signal.size_usd, 2),
                "aligned_wallets": aligned_wallets,
            },
        )

    def aggregate_strategy_decisions(
        self,
        s1_decision: StrategyDecision,
        s2_decision: CrossExchangeArbitrageDecision,
        s3_decision: SmartMoneyCopyTradingDecision,
    ) -> StrategyAggregationDecision:
        """
        Aggregate S1/S2/S3 strategy outputs and select one best trade candidate.
        """
        candidates = [
            self._build_strategy_candidate_score(
                strategy_name="S1",
                decision=s1_decision.decision,
                reason=s1_decision.reason,
                edge=s1_decision.edge,
                confidence=None,
                market_metadata={},
            ),
            self._build_strategy_candidate_score(
                strategy_name="S2",
                decision=s2_decision.decision,
                reason=s2_decision.reason,
                edge=s2_decision.edge,
                confidence=None,
                market_metadata=s2_decision.matched_markets_info,
            ),
            self._build_strategy_candidate_score(
                strategy_name="S3",
                decision=s3_decision.decision,
                reason=s3_decision.reason,
                edge=max(0.0, s3_decision.confidence * self._config.min_edge),
                confidence=s3_decision.confidence,
                market_metadata=s3_decision.wallet_info,
            ),
        ]
        ranked_candidates = sorted(candidates, key=lambda item: (-item.score, item.strategy_name))
        enter_candidates = [candidate for candidate in ranked_candidates if candidate.decision == "ENTER"]
        top_score = ranked_candidates[0].score if ranked_candidates else 0.0
        min_score_threshold = 0.40
        has_global_conflict_hold = any(
            candidate.reason.upper().startswith("CONFLICT_HOLD")
            for candidate in enter_candidates
        )
        if not enter_candidates:
            return StrategyAggregationDecision(
                selected_trade=None,
                ranked_candidates=ranked_candidates,
                selection_reason="all candidates are SKIP",
                top_score=top_score,
                decision="SKIP",
            )

        if has_global_conflict_hold:
            return StrategyAggregationDecision(
                selected_trade=None,
                ranked_candidates=ranked_candidates,
                selection_reason="conflict rules require holding",
                top_score=top_score,
                decision="SKIP",
            )

        top_candidate = enter_candidates[0]
        if top_candidate.score < min_score_threshold:
            return StrategyAggregationDecision(
                selected_trade=None,
                ranked_candidates=ranked_candidates,
                selection_reason="all candidates are weak",
                top_score=top_score,
                decision="SKIP",
            )

        return StrategyAggregationDecision(
            selected_trade=top_candidate.strategy_name,
            ranked_candidates=ranked_candidates,
            selection_reason=f"selected highest-ranked candidate: {top_candidate.strategy_name}",
            top_score=top_candidate.score,
            decision="ENTER",
        )

    def _build_strategy_candidate_score(
        self,
        strategy_name: str,
        decision: str,
        reason: str,
        edge: float,
        confidence: float | None,
        market_metadata: dict[str, object],
    ) -> StrategyCandidateScore:
        normalized_edge = min(max(edge, 0.0) / 0.10, 1.0)
        normalized_confidence = (
            min(max(confidence, 0.0), 1.0)
            if confidence is not None
            else 0.5
        )
        score = round((0.7 * normalized_edge) + (0.3 * normalized_confidence), 6)
        return StrategyCandidateScore(
            strategy_name=strategy_name,
            decision=decision,
            reason=reason,
            edge=round(max(edge, 0.0), 6),
            confidence=round(normalized_confidence, 6),
            score=score,
            market_metadata=market_metadata,
        )

    def compute_position_size_from_s4_selection(
        self,
        aggregation: StrategyAggregationDecision,
        total_capital: float,
        current_total_exposure: float,
    ) -> PositionSizingDecision:
        if aggregation.decision != "ENTER" or not aggregation.selected_trade:
            return PositionSizingDecision(
                position_size=0.0,
                size_reason="no selected S4 trade",
                applied_constraints=("selection_skip",),
                normalized_score=0.0,
            )

        selected_candidate = next(
            (item for item in aggregation.ranked_candidates if item.strategy_name == aggregation.selected_trade),
            None,
        )
        if selected_candidate is None:
            return PositionSizingDecision(
                position_size=0.0,
                size_reason="selected trade missing from ranked candidates",
                applied_constraints=("selection_mismatch",),
                normalized_score=0.0,
            )

        return self._compute_position_size(
            strategy_name=selected_candidate.strategy_name,
            edge=selected_candidate.edge,
            confidence=(
                None
                if selected_candidate.strategy_name in {"S1", "S2"}
                else selected_candidate.confidence
            ),
            total_capital=total_capital,
            current_total_exposure=current_total_exposure,
        )

    def _compute_position_size(
        self,
        strategy_name: str,
        edge: float,
        confidence: float | None,
        total_capital: float,
        current_total_exposure: float,
    ) -> PositionSizingDecision:
        safe_capital = max(total_capital, 0.0)
        max_position_size = safe_capital * self._config.max_position_size_ratio
        max_total_exposure = safe_capital * self._engine.max_total_exposure_ratio
        available_exposure = max(0.0, max_total_exposure - max(current_total_exposure, 0.0))
        applied_constraints: list[str] = []

        confidence_missing = confidence is None
        confidence_val = (
            0.35
            if confidence_missing
            else min(max(confidence, 0.0), 1.0)
        )
        edge_val = max(edge, 0.0)
        edge_norm = min(edge_val / 0.10, 1.0)
        base_score = (0.7 * edge_norm) + (0.3 * confidence_val)

        conservative_multiplier = 1.0
        if confidence_missing:
            conservative_multiplier *= 0.7
            applied_constraints.append("confidence_missing_conservative")
        if edge_val <= (self._config.min_edge * 1.2):
            conservative_multiplier *= 0.5
            applied_constraints.append("borderline_edge_conservative")

        normalized_score = min(max(base_score * conservative_multiplier, 0.0), 1.0)
        scaled_score = normalized_score ** 2
        raw_position_size = safe_capital * self._config.max_position_size_ratio * scaled_score
        position_size = raw_position_size

        if position_size > max_position_size:
            position_size = max_position_size
            applied_constraints.append("max_position_size_cap")

        if position_size > available_exposure:
            position_size = available_exposure
            applied_constraints.append("total_exposure_cap")

        if 0.0 < position_size < self._config.min_position_size_usd:
            position_size = 0.0
            applied_constraints.append("min_position_size_floor")

        reason_suffix = ", ".join(applied_constraints) if applied_constraints else "no constraints applied"
        size_reason = (
            f"{strategy_name} sizing from edge/confidence score={normalized_score:.4f}; "
            f"{reason_suffix}"
        )
        return PositionSizingDecision(
            position_size=round(max(position_size, 0.0), 2),
            size_reason=size_reason,
            applied_constraints=tuple(applied_constraints),
            normalized_score=round(normalized_score, 6),
        )

    def _select_best_cross_exchange_match(
        self,
        polymarket: CrossExchangeMarket,
        kalshi_markets: list[CrossExchangeMarket],
    ) -> tuple[CrossExchangeMarket | None, float]:
        best_market: CrossExchangeMarket | None = None
        best_score = 0.0
        poly_tokens = set(self._tokenize(polymarket.title))

        for candidate in kalshi_markets:
            candidate_tokens = set(self._tokenize(candidate.title))
            overlap = len(poly_tokens & candidate_tokens)
            overlap_score = min(
                1.0,
                overlap / max(float(self._config.cross_exchange_min_overlap_tokens), 1.0),
            )
            event_match = 1.0 if polymarket.event_key and polymarket.event_key == candidate.event_key else 0.0
            timeframe_match = 1.0 if polymarket.timeframe and polymarket.timeframe == candidate.timeframe else 0.0
            resolution_match = (
                1.0
                if polymarket.resolution_criteria
                and polymarket.resolution_criteria == candidate.resolution_criteria
                else 0.0
            )
            score = (0.4 * event_match) + (0.2 * timeframe_match) + (0.2 * resolution_match) + (0.2 * overlap_score)
            if score > best_score:
                best_score = score
                best_market = candidate

        return best_market, best_score

    @staticmethod
    def _normalize_probability(raw_probability: float) -> float:
        if raw_probability <= 1.0:
            return min(max(raw_probability, 0.0), 1.0)
        if raw_probability <= 100.0:
            return min(max(raw_probability / 100.0, 0.0), 1.0)
        return 1.0

    @staticmethod
    def _bps_to_probability(value_bps: float) -> float:
        return max(value_bps, 0.0) / 10_000.0

    @staticmethod
    def _tokenize(value: str) -> list[str]:
        return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if len(token) >= 3]

    async def evaluate(
        self,
        market_price: float,
        aggregation_decision: StrategyAggregationDecision | None = None,
    ) -> str:
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
            current_total_exposure = sum(position.exposure() for position in snapshot.positions)
            sizing = (
                self.compute_position_size_from_s4_selection(
                    aggregation=aggregation_decision,
                    total_capital=snapshot.equity,
                    current_total_exposure=current_total_exposure,
                )
                if aggregation_decision is not None
                else PositionSizingDecision(
                    position_size=round(snapshot.equity * self._engine.max_position_size_ratio, 2),
                    size_reason="fallback fixed sizing (no S4 aggregation decision provided)",
                    applied_constraints=("fallback_fixed_sizing",),
                    normalized_score=1.0,
                )
            )
            size = sizing.position_size
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
