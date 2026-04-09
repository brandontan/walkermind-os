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
    settlement_gap_underpriced_threshold: float = 0.95
    settlement_gap_min_mapping_confidence: float = 0.60
    min_position_size_usd: float = 25.0
    max_position_size_ratio: float = 0.10
    max_market_exposure_ratio: float = 0.15
    max_theme_exposure_ratio: float = 0.20
    correlation_size_reduction_factor: float = 0.50
    high_similarity_overlap_ratio: float = 0.60
    max_execution_spread: float = 0.04
    borderline_execution_spread: float = 0.025
    min_execution_depth_usd: float = 10_000.0
    borderline_execution_depth_usd: float = 20_000.0
    max_slippage_edge_consumption_ratio: float = 0.60
    borderline_slippage_edge_consumption_ratio: float = 0.35
    execution_reduction_factor: float = 0.50
    anti_chase_extension_ratio: float = 0.025
    anti_chase_spread_ratio: float = 0.030
    micro_pullback_improvement_ratio: float = 0.008
    timing_reevaluation_window_seconds: int = 15
    timing_max_wait_cycles: int = 2
    stop_loss_ratio: float = 0.04
    favorable_pnl_ratio: float = 0.015
    momentum_weakening_ratio: float = 0.35
    stale_trade_price_move_ratio: float = 0.003
    max_trade_duration_seconds: int = 1800
    hard_max_trade_duration_seconds: int = 3600
    fast_exit_regime_factor: float = 0.75
    slow_exit_regime_factor: float = 1.25


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
class KalshiResolvedMarket:
    market_id: str
    title: str
    resolved: bool
    resolved_outcome: str
    event_key: str = ""
    timeframe: str = ""
    resolution_criteria: str = ""


@dataclass(frozen=True)
class PolymarketSettlementMarket:
    market_id: str
    title: str
    yes_price: float
    liquidity_usd: float
    orderbook_depth_usd: float
    is_open: bool = True
    event_key: str = ""
    timeframe: str = ""
    resolution_criteria: str = ""


@dataclass(frozen=True)
class SettlementGapDecision:
    decision: str
    reason: str
    edge: float
    source: str


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
    h_score: float
    consistency_score: float
    discipline_score: float
    trade_frequency_score: float
    market_diversity_score: float


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
    current_regime: str = "LOW_ACTIVITY_CHAOTIC"
    regime_confidence: float = 0.0
    strategy_weight_modifiers: dict[str, float] | None = None


@dataclass(frozen=True)
class PositionSizingDecision:
    position_size: float
    size_reason: str
    applied_constraints: tuple[str, ...]
    normalized_score: float


@dataclass(frozen=True)
class PortfolioExposureDecision:
    final_decision: str
    adjusted_size: float
    reason: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionQualityDecision:
    final_decision: str
    adjusted_size: float
    expected_fill_price: float
    expected_slippage: float
    execution_quality_reason: str


@dataclass(frozen=True)
class EntryTimingDecision:
    timing_decision: str
    timing_reason: str
    reference_price: float
    reevaluation_window: int
    final_execution_readiness: bool


@dataclass(frozen=True)
class EntryExecutionReadiness:
    timing_decision: str
    timing_reason: str
    reference_price: float
    reevaluation_window: int
    final_execution_readiness: bool
    execution_quality_decision: str
    execution_quality_reason: str
    adjusted_size: float
    expected_fill_price: float
    expected_slippage: float


@dataclass(frozen=True)
class ExitDecision:
    exit_decision: str
    exit_reason: str
    pnl_snapshot: float
    trade_duration: int


@dataclass(frozen=True)
class StrategyPerformanceStats:
    strategy_name: str
    total_trades: int
    wins: int
    losses: int
    average_edge: float
    average_pnl: float
    average_return: float
    win_rate: float
    consistency_score: float


@dataclass(frozen=True)
class AdaptiveAdjustmentState:
    strategy_weights: dict[str, float]
    sizing_modifier: float
    min_edge_threshold: float
    confidence_threshold: float
    explanation: str


@dataclass(frozen=True)
class MarketRegimeInputs:
    social_spike_intensity: float
    price_dispersion: float
    wallet_activity_strength: float
    trade_frequency: float
    volatility: float


@dataclass(frozen=True)
class MarketRegimeClassification:
    regime_type: str
    confidence_score: float
    strategy_weight_modifiers: dict[str, float]


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
        self._strategy_results: dict[str, list[dict[str, float]]] = {}
        self._adaptive_weights: dict[str, float] = {"S1": 1.0, "S2": 1.0, "S3": 1.0}
        self._adaptive_sizing_modifier: float = 1.0
        self._adaptive_edge_threshold: float = self._config.min_edge
        self._adaptive_confidence_threshold: float = 0.65
        self._adaptive_min_trades: int = 5
        self._adaptive_step_limit: float = 0.03
        self._adaptive_weight_bounds: tuple[float, float] = (0.80, 1.20)
        self._adaptive_sizing_bounds: tuple[float, float] = (0.85, 1.15)
        self._adaptive_edge_bounds: tuple[float, float] = (
            max(0.005, self._config.min_edge * 0.80),
            self._config.min_edge * 1.20,
        )
        self._adaptive_confidence_bounds: tuple[float, float] = (0.55, 0.80)
        self._last_adjustment_explanation: str = "adaptive defaults active"
        self._position_peak_pnl: dict[str, float] = {}
        self._position_entry_context: dict[str, dict[str, object]] = {}

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return min(max(value, lower), upper)

    def record_trade_result(
        self,
        *,
        strategy_name: str,
        pnl: float,
        edge: float,
        position_size: float,
    ) -> None:
        normalized_strategy = strategy_name.strip().upper()
        if normalized_strategy not in self._adaptive_weights:
            return
        safe_size = max(position_size, 1e-6)
        trade_return = pnl / safe_size
        bucket = self._strategy_results.setdefault(normalized_strategy, [])
        bucket.append(
            {
                "pnl": pnl,
                "edge": max(edge, 0.0),
                "return": trade_return,
            }
        )
        if len(bucket) > 50:
            del bucket[0]
        self._refresh_adaptive_state()

    def _compute_strategy_performance(self, strategy_name: str) -> StrategyPerformanceStats:
        results = self._strategy_results.get(strategy_name, [])
        if not results:
            return StrategyPerformanceStats(
                strategy_name=strategy_name,
                total_trades=0,
                wins=0,
                losses=0,
                average_edge=0.0,
                average_pnl=0.0,
                average_return=0.0,
                win_rate=0.0,
                consistency_score=0.0,
            )
        total = len(results)
        wins = sum(1 for item in results if item["pnl"] > 0.0)
        losses = total - wins
        avg_edge = sum(item["edge"] for item in results) / total
        avg_pnl = sum(item["pnl"] for item in results) / total
        avg_return = sum(item["return"] for item in results) / total
        mean_abs_return = sum(abs(item["return"]) for item in results) / total
        consistency = avg_return / max(mean_abs_return, 1e-6)
        return StrategyPerformanceStats(
            strategy_name=strategy_name,
            total_trades=total,
            wins=wins,
            losses=losses,
            average_edge=round(avg_edge, 6),
            average_pnl=round(avg_pnl, 6),
            average_return=round(avg_return, 6),
            win_rate=round(wins / total, 6),
            consistency_score=round(self._clamp(consistency, -1.0, 1.0), 6),
        )

    def _refresh_adaptive_state(self) -> None:
        metrics = {
            name: self._compute_strategy_performance(name)
            for name in self._adaptive_weights
        }
        mature_metrics = [
            item
            for item in metrics.values()
            if item.total_trades >= self._adaptive_min_trades
        ]
        if not mature_metrics:
            self._adaptive_weights = {"S1": 1.0, "S2": 1.0, "S3": 1.0}
            self._adaptive_sizing_modifier = 1.0
            self._adaptive_edge_threshold = self._config.min_edge
            self._adaptive_confidence_threshold = 0.65
            self._last_adjustment_explanation = "insufficient data; fallback to defaults"
            return

        target_weights: dict[str, float] = {}
        for strategy_name, snapshot in metrics.items():
            if snapshot.total_trades < self._adaptive_min_trades:
                target_weights[strategy_name] = 1.0
                continue
            score_signal = (
                (snapshot.win_rate - 0.5) * 0.60
                + snapshot.consistency_score * 0.25
                + self._clamp(snapshot.average_return, -0.10, 0.10) * 1.50
            )
            raw_weight = 1.0 + score_signal
            target_weights[strategy_name] = self._clamp(
                raw_weight,
                self._adaptive_weight_bounds[0],
                self._adaptive_weight_bounds[1],
            )
        self._adaptive_weights = {
            name: round(
                current + self._clamp(target_weights[name] - current, -self._adaptive_step_limit, self._adaptive_step_limit),
                6,
            )
            for name, current in self._adaptive_weights.items()
        }

        aggregate_return = sum(item.average_return for item in mature_metrics) / len(mature_metrics)
        aggregate_consistency = sum(item.consistency_score for item in mature_metrics) / len(mature_metrics)
        sizing_target = self._clamp(
            1.0 + (aggregate_return * 1.2) + (aggregate_consistency * 0.08),
            self._adaptive_sizing_bounds[0],
            self._adaptive_sizing_bounds[1],
        )
        self._adaptive_sizing_modifier = round(
            self._adaptive_sizing_modifier
            + self._clamp(sizing_target - self._adaptive_sizing_modifier, -self._adaptive_step_limit, self._adaptive_step_limit),
            6,
        )

        edge_target = self._clamp(
            self._config.min_edge - (aggregate_return * 0.01),
            self._adaptive_edge_bounds[0],
            self._adaptive_edge_bounds[1],
        )
        self._adaptive_edge_threshold = round(
            self._adaptive_edge_threshold
            + self._clamp(edge_target - self._adaptive_edge_threshold, -0.002, 0.002),
            6,
        )

        confidence_target = self._clamp(
            0.65 - (aggregate_return * 0.30),
            self._adaptive_confidence_bounds[0],
            self._adaptive_confidence_bounds[1],
        )
        self._adaptive_confidence_threshold = round(
            self._adaptive_confidence_threshold
            + self._clamp(confidence_target - self._adaptive_confidence_threshold, -0.015, 0.015),
            6,
        )
        self._last_adjustment_explanation = (
            f"adaptive update from {len(mature_metrics)} mature strategy histories; "
            f"aggregate_return={aggregate_return:.5f}, aggregate_consistency={aggregate_consistency:.5f}"
        )

    def get_adaptive_adjustment_state(self) -> AdaptiveAdjustmentState:
        return AdaptiveAdjustmentState(
            strategy_weights=dict(self._adaptive_weights),
            sizing_modifier=round(self._adaptive_sizing_modifier, 6),
            min_edge_threshold=round(self._adaptive_edge_threshold, 6),
            confidence_threshold=round(self._adaptive_confidence_threshold, 6),
            explanation=self._last_adjustment_explanation,
        )

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

        adaptive_min_edge = self.get_adaptive_adjustment_state().min_edge_threshold
        if edge <= adaptive_min_edge:
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

    def evaluate_settlement_gap_scanner(
        self,
        kalshi_market: KalshiResolvedMarket,
        polymarket_markets: list[PolymarketSettlementMarket],
    ) -> SettlementGapDecision:
        source = "settlement_gap"
        if not kalshi_market.resolved:
            return SettlementGapDecision(
                decision="SKIP",
                reason="clear resolution signal missing",
                edge=0.0,
                source=source,
            )

        normalized_outcome = kalshi_market.resolved_outcome.strip().upper()
        if normalized_outcome not in {"YES", "NO"}:
            return SettlementGapDecision(
                decision="SKIP",
                reason="clear resolution signal missing",
                edge=0.0,
                source=source,
            )

        best_match, confidence = self._select_best_settlement_gap_match(
            kalshi_market=kalshi_market,
            polymarket_markets=polymarket_markets,
        )
        if best_match is None or confidence < self._config.settlement_gap_min_mapping_confidence:
            return SettlementGapDecision(
                decision="SKIP",
                reason="mapping uncertain",
                edge=0.0,
                source=source,
            )

        if not best_match.is_open:
            return SettlementGapDecision(
                decision="SKIP",
                reason="market closed / illiquid",
                edge=0.0,
                source=source,
            )

        available_depth = min(best_match.liquidity_usd, best_match.orderbook_depth_usd)
        if available_depth < self._config.min_liquidity_usd:
            return SettlementGapDecision(
                decision="SKIP",
                reason="liquidity insufficient",
                edge=0.0,
                source=source,
            )

        yes_price = self._normalize_probability(best_match.yes_price)
        resolved_outcome_price = yes_price if normalized_outcome == "YES" else (1.0 - yes_price)
        edge = max(0.0, 1.0 - resolved_outcome_price)
        if resolved_outcome_price >= self._config.settlement_gap_underpriced_threshold:
            return SettlementGapDecision(
                decision="SKIP",
                reason="already converged",
                edge=round(edge, 6),
                source=source,
            )

        return SettlementGapDecision(
            decision="ENTER",
            reason="settlement gap opportunity detected",
            edge=round(edge, 6),
            source=source,
        )

    def _compute_wallet_quality_score(self, signal: WalletTradeSignal) -> float:
        h_component = self._clamp(signal.h_score / 100.0, 0.0, 1.0)
        consistency_component = self._clamp(signal.consistency_score, 0.0, 1.0)
        discipline_component = self._clamp(signal.discipline_score, 0.0, 1.0)
        diversity_component = self._clamp(signal.market_diversity_score, 0.0, 1.0)
        return round(
            (0.40 * h_component)
            + (0.25 * consistency_component)
            + (0.20 * discipline_component)
            + (0.15 * diversity_component),
            6,
        )

    def evaluate_smart_money_copy_trading(
        self,
        signal: WalletTradeSignal,
        related_wallet_signals: list[WalletTradeSignal],
    ) -> SmartMoneyCopyTradingDecision:
        min_h_score = 65.0
        min_success_rate = 0.60
        min_activity_count = 15
        min_consistency_score = 0.55
        min_wallet_quality_score = 0.68
        bot_like_frequency_threshold = 0.95
        erratic_frequency_threshold = 0.10
        large_position_usd = 10_000.0
        early_entry_max_move_pct = 0.02
        repeated_wallet_min_count = 2
        min_confidence_threshold = self.get_adaptive_adjustment_state().confidence_threshold
        wallet_quality_score = self._compute_wallet_quality_score(signal)

        if signal.h_score < min_h_score:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="wallet quality skip: h-score below threshold",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "h_score": round(signal.h_score, 4),
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        if signal.wallet_success_rate < min_success_rate or signal.wallet_activity_count < min_activity_count:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="wallet quality skip: low-quality wallet profile",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "success_rate": round(signal.wallet_success_rate, 4),
                    "activity_count": signal.wallet_activity_count,
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        if signal.consistency_score < min_consistency_score:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="wallet quality skip: poor consistency",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "consistency": round(signal.consistency_score, 6),
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        if signal.trade_frequency_score >= bot_like_frequency_threshold:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="wallet quality skip: bot-like activity",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "trade_frequency": round(signal.trade_frequency_score, 6),
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        if signal.trade_frequency_score <= erratic_frequency_threshold:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="wallet quality skip: erratic behavior",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "trade_frequency": round(signal.trade_frequency_score, 6),
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        if wallet_quality_score <= min_wallet_quality_score:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="wallet quality skip: score below threshold",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "wallet_quality_score": wallet_quality_score,
                    "h_score": round(signal.h_score, 4),
                    "consistency": round(signal.consistency_score, 6),
                    "discipline": round(signal.discipline_score, 6),
                    "diversity": round(signal.market_diversity_score, 6),
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
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        if signal.action.lower() not in {"buy", "sell"}:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="conflicting signals",
                confidence=0.0,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "wallet_quality_score": wallet_quality_score,
                },
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
                    "wallet_quality_score": wallet_quality_score,
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
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        size_score = min(1.0, signal.size_usd / large_position_usd)
        early_score = max(0.0, 1.0 - (signal.market_move_pct / early_entry_max_move_pct))
        aligned_wallets = sum(1 for item in same_market_signals if item.action.lower() == signal.action.lower())
        repeated_score = min(1.0, aligned_wallets / max(float(repeated_wallet_min_count), 1.0))
        confidence = round((0.35 * size_score) + (0.20 * early_score) + (0.20 * repeated_score) + (0.25 * wallet_quality_score), 6)

        if confidence <= min_confidence_threshold:
            return SmartMoneyCopyTradingDecision(
                decision="SKIP",
                reason="signal strength below threshold with wallet quality context",
                confidence=confidence,
                wallet_info={
                    "wallet_address": signal.wallet_address,
                    "aligned_wallets": aligned_wallets,
                    "wallet_quality_score": wallet_quality_score,
                },
            )

        return SmartMoneyCopyTradingDecision(
            decision="ENTER",
            reason="high-quality wallet signal accepted",
            confidence=confidence,
            wallet_info={
                "wallet_address": signal.wallet_address,
                "action": signal.action.upper(),
                "success_rate": round(signal.wallet_success_rate, 4),
                "activity_count": signal.wallet_activity_count,
                "size_usd": round(signal.size_usd, 2),
                "aligned_wallets": aligned_wallets,
                "h_score": round(signal.h_score, 4),
                "consistency": round(signal.consistency_score, 6),
                "discipline": round(signal.discipline_score, 6),
                "trade_frequency": round(signal.trade_frequency_score, 6),
                "diversity": round(signal.market_diversity_score, 6),
                "wallet_quality_score": wallet_quality_score,
            },
        )

    def aggregate_strategy_decisions(
        self,
        s1_decision: StrategyDecision,
        s2_decision: CrossExchangeArbitrageDecision,
        s3_decision: SmartMoneyCopyTradingDecision,
        market_regime_inputs: MarketRegimeInputs | None = None,
    ) -> StrategyAggregationDecision:
        """
        Aggregate S1/S2/S3 strategy outputs and select one best trade candidate.
        """
        regime = (
            self.detect_market_regime(market_regime_inputs)
            if market_regime_inputs is not None
            else MarketRegimeClassification(
                regime_type="LOW_ACTIVITY_CHAOTIC",
                confidence_score=0.0,
                strategy_weight_modifiers={"S1": 1.0, "S2": 1.0, "S3": 1.0},
            )
        )
        candidates = [
            self._build_strategy_candidate_score(
                strategy_name="S1",
                decision=s1_decision.decision,
                reason=s1_decision.reason,
                edge=s1_decision.edge,
                confidence=None,
                market_metadata={},
                regime_weight_modifier=regime.strategy_weight_modifiers.get("S1", 1.0),
            ),
            self._build_strategy_candidate_score(
                strategy_name="S2",
                decision=s2_decision.decision,
                reason=s2_decision.reason,
                edge=s2_decision.edge,
                confidence=None,
                market_metadata=s2_decision.matched_markets_info,
                regime_weight_modifier=regime.strategy_weight_modifiers.get("S2", 1.0),
            ),
            self._build_strategy_candidate_score(
                strategy_name="S3",
                decision=s3_decision.decision,
                reason=s3_decision.reason,
                edge=max(0.0, s3_decision.confidence * self._config.min_edge),
                confidence=s3_decision.confidence,
                market_metadata=s3_decision.wallet_info,
                regime_weight_modifier=regime.strategy_weight_modifiers.get("S3", 1.0),
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
                current_regime=regime.regime_type,
                regime_confidence=regime.confidence_score,
                strategy_weight_modifiers=regime.strategy_weight_modifiers,
            )

        if has_global_conflict_hold:
            return StrategyAggregationDecision(
                selected_trade=None,
                ranked_candidates=ranked_candidates,
                selection_reason="conflict rules require holding",
                top_score=top_score,
                decision="SKIP",
                current_regime=regime.regime_type,
                regime_confidence=regime.confidence_score,
                strategy_weight_modifiers=regime.strategy_weight_modifiers,
            )

        top_candidate = enter_candidates[0]
        if top_candidate.score < min_score_threshold:
            return StrategyAggregationDecision(
                selected_trade=None,
                ranked_candidates=ranked_candidates,
                selection_reason="all candidates are weak",
                top_score=top_score,
                decision="SKIP",
                current_regime=regime.regime_type,
                regime_confidence=regime.confidence_score,
                strategy_weight_modifiers=regime.strategy_weight_modifiers,
            )

        return StrategyAggregationDecision(
            selected_trade=top_candidate.strategy_name,
            ranked_candidates=ranked_candidates,
            selection_reason=f"selected highest-ranked candidate: {top_candidate.strategy_name}",
            top_score=top_candidate.score,
            decision="ENTER",
            current_regime=regime.regime_type,
            regime_confidence=regime.confidence_score,
            strategy_weight_modifiers=regime.strategy_weight_modifiers,
        )

    def detect_market_regime(
        self,
        inputs: MarketRegimeInputs,
    ) -> MarketRegimeClassification:
        social_score = self._clamp(inputs.social_spike_intensity, 0.0, 1.0)
        dispersion_score = self._clamp(inputs.price_dispersion, 0.0, 1.0)
        wallet_score = self._clamp(inputs.wallet_activity_strength, 0.0, 1.0)
        activity_score = self._clamp((inputs.trade_frequency * 0.50) + (inputs.volatility * 0.50), 0.0, 1.0)
        dominant_signal = max(social_score, dispersion_score, wallet_score)

        regime_type = "LOW_ACTIVITY_CHAOTIC"
        confidence = round(self._clamp(0.50 + (activity_score * 0.20), 0.0, 1.0), 6)
        if social_score >= 0.70 and social_score >= (dispersion_score + 0.10) and social_score >= (wallet_score + 0.10):
            regime_type = "NEWS_DRIVEN"
            confidence = round(self._clamp(0.55 + (social_score * 0.45), 0.0, 1.0), 6)
        elif dispersion_score >= 0.65 and dispersion_score >= (wallet_score + 0.05):
            regime_type = "ARBITRAGE_DOMINANT"
            confidence = round(self._clamp(0.55 + (dispersion_score * 0.45), 0.0, 1.0), 6)
        elif wallet_score >= 0.65:
            regime_type = "SMART_MONEY_DOMINANT"
            confidence = round(self._clamp(0.55 + (wallet_score * 0.45), 0.0, 1.0), 6)
        elif dominant_signal < 0.45 or activity_score >= 0.75:
            regime_type = "LOW_ACTIVITY_CHAOTIC"
            confidence = round(self._clamp(0.50 + ((1.0 - dominant_signal) * 0.30), 0.0, 1.0), 6)

        weight_modifiers = self._build_regime_weight_modifiers(
            regime_type=regime_type,
            confidence_score=confidence,
        )
        return MarketRegimeClassification(
            regime_type=regime_type,
            confidence_score=confidence,
            strategy_weight_modifiers=weight_modifiers,
        )

    def _build_regime_weight_modifiers(
        self,
        *,
        regime_type: str,
        confidence_score: float,
    ) -> dict[str, float]:
        neutral = {"S1": 1.0, "S2": 1.0, "S3": 1.0}
        bounded_regime_modifiers = {
            "NEWS_DRIVEN": {"S1": 1.18, "S2": 0.94, "S3": 0.94},
            "ARBITRAGE_DOMINANT": {"S1": 0.94, "S2": 1.18, "S3": 0.94},
            "SMART_MONEY_DOMINANT": {"S1": 0.94, "S2": 0.94, "S3": 1.18},
            "LOW_ACTIVITY_CHAOTIC": {"S1": 0.90, "S2": 0.90, "S3": 0.90},
        }
        selected = bounded_regime_modifiers.get(regime_type, neutral)
        if confidence_score < 0.60:
            selected = neutral
        return {
            strategy: round(self._clamp(modifier, 0.85, 1.20), 6)
            for strategy, modifier in selected.items()
        }

    def _build_strategy_candidate_score(
        self,
        strategy_name: str,
        decision: str,
        reason: str,
        edge: float,
        confidence: float | None,
        market_metadata: dict[str, object],
        regime_weight_modifier: float = 1.0,
    ) -> StrategyCandidateScore:
        normalized_edge = min(max(edge, 0.0) / 0.10, 1.0)
        normalized_confidence = (
            min(max(confidence, 0.0), 1.0)
            if confidence is not None
            else 0.5
        )
        score = round((0.7 * normalized_edge) + (0.3 * normalized_confidence), 6)
        adaptive_weight = self._adaptive_weights.get(strategy_name, 1.0)
        bounded_regime_modifier = self._clamp(regime_weight_modifier, 0.85, 1.20)
        weighted_score = round(score * adaptive_weight * bounded_regime_modifier, 6)
        return StrategyCandidateScore(
            strategy_name=strategy_name,
            decision=decision,
            reason=reason,
            edge=round(max(edge, 0.0), 6),
            confidence=round(normalized_confidence, 6),
            score=weighted_score,
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
        raw_position_size *= self._adaptive_sizing_modifier
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

    def evaluate_portfolio_exposure_and_correlation(
        self,
        *,
        target_market_id: str,
        target_theme: str | None,
        proposed_size: float,
        open_positions: list[object],
        total_capital: float,
    ) -> PortfolioExposureDecision:
        safe_capital = max(total_capital, 0.0)
        if proposed_size <= 0.0 or safe_capital <= 0.0:
            return PortfolioExposureDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                reason="invalid proposed size or capital",
                flags=("invalid_input",),
            )

        current_total_exposure = sum(max(float(position.exposure()), 0.0) for position in open_positions)
        total_exposure_cap = safe_capital * self._engine.max_total_exposure_ratio
        available_total_exposure = max(0.0, total_exposure_cap - current_total_exposure)
        if available_total_exposure <= 0.0:
            return PortfolioExposureDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                reason="total exposure cap reached",
                flags=("total_exposure_cap",),
            )

        same_market_exposure = sum(
            max(float(position.exposure()), 0.0)
            for position in open_positions
            if getattr(position, "market_id", "") == target_market_id
        )
        if same_market_exposure > 0.0:
            return PortfolioExposureDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                reason="correlated exposure: same market already open",
                flags=("same_market_block",),
            )

        normalized_target_theme = (target_theme or "").strip().lower()
        theme_exposure = 0.0
        if normalized_target_theme:
            theme_exposure = sum(
                max(float(position.exposure()), 0.0)
                for position in open_positions
                if self._infer_position_theme(position) == normalized_target_theme
            )
            theme_cap = safe_capital * self._config.max_theme_exposure_ratio
            if theme_exposure >= theme_cap:
                return PortfolioExposureDecision(
                    final_decision="SKIP",
                    adjusted_size=0.0,
                    reason="theme exposure cap reached",
                    flags=("theme_exposure_cap",),
                )

        max_market_exposure = safe_capital * self._config.max_market_exposure_ratio
        market_headroom = max(0.0, max_market_exposure - same_market_exposure)
        final_size = min(proposed_size, available_total_exposure, market_headroom)
        flags: list[str] = []
        reason = "portfolio fit validated"

        if normalized_target_theme:
            theme_cap = safe_capital * self._config.max_theme_exposure_ratio
            theme_headroom = max(0.0, theme_cap - theme_exposure)
            if final_size > theme_headroom:
                final_size = theme_headroom
                flags.append("theme_exposure_cap")

        if self._has_high_similarity_overlap(target_market_id=target_market_id, open_positions=open_positions):
            reduced_size = final_size * self._config.correlation_size_reduction_factor
            final_size = min(final_size, reduced_size)
            flags.append("high_similarity_reduce")
            reason = "correlated exposure: highly similar condition"

        if final_size <= 0.0:
            return PortfolioExposureDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                reason=reason if flags else "portfolio exposure constraint",
                flags=tuple(flags or ["no_available_exposure"]),
            )

        if 0.0 < final_size < self._config.min_position_size_usd:
            return PortfolioExposureDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                reason="adjusted size below minimum threshold",
                flags=tuple(flags + ["min_position_size_floor"]),
            )

        if final_size < proposed_size:
            if not reason.startswith("correlated exposure"):
                reason = "exposure cap adjustment"
            return PortfolioExposureDecision(
                final_decision="REDUCE",
                adjusted_size=round(final_size, 2),
                reason=reason,
                flags=tuple(flags or ["exposure_reduce"]),
            )

        return PortfolioExposureDecision(
            final_decision="ENTER",
            adjusted_size=round(final_size, 2),
            reason=reason,
            flags=tuple(flags),
        )

    def _resolve_candidate_market_context(
        self,
        selected_candidate: StrategyCandidateScore | None,
    ) -> tuple[str, str | None]:
        if selected_candidate is None:
            return self._config.market_id, None
        metadata = selected_candidate.market_metadata or {}
        raw_market_id = (
            metadata.get("market_id")
            or metadata.get("polymarket")
            or self._config.market_id
        )
        market_id = str(raw_market_id)
        raw_theme = (
            metadata.get("theme")
            or metadata.get("event_key")
            or metadata.get("event")
            or metadata.get("category")
        )
        theme = str(raw_theme).strip() if raw_theme is not None else None
        return market_id, theme

    @staticmethod
    def _infer_position_theme(position: object) -> str:
        for attr in ("theme", "event_key", "category"):
            value = getattr(position, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return ""

    def _has_high_similarity_overlap(
        self,
        *,
        target_market_id: str,
        open_positions: list[object],
    ) -> bool:
        target_tokens = set(self._tokenize(target_market_id))
        if not target_tokens:
            return False
        for position in open_positions:
            market_id = str(getattr(position, "market_id", ""))
            if not market_id or market_id == target_market_id:
                continue
            position_tokens = set(self._tokenize(market_id))
            if not position_tokens:
                continue
            overlap = len(target_tokens & position_tokens)
            overlap_ratio = overlap / max(len(target_tokens), len(position_tokens))
            if overlap_ratio >= self._config.high_similarity_overlap_ratio:
                return True
        return False

    def evaluate_execution_quality(
        self,
        *,
        market_price: float,
        proposed_size: float,
        signal_edge: float,
        market_context: dict[str, float] | None = None,
    ) -> ExecutionQualityDecision:
        context = market_context or {}
        size = max(0.0, proposed_size)
        if size <= 0.0:
            return ExecutionQualityDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                expected_fill_price=round(max(market_price, 0.0), 6),
                expected_slippage=0.0,
                execution_quality_reason="insufficient_depth",
            )

        spread_val = float(context.get("spread", 0.0))
        if spread_val < 0.0:
            spread_val = 0.0
        bid = float(context.get("best_bid", max(0.0, market_price - (spread_val / 2.0))))
        ask = float(context.get("best_ask", min(1.0, market_price + (spread_val / 2.0))))
        observed_spread = max(0.0, ask - bid, spread_val)

        if observed_spread >= self._config.max_execution_spread:
            expected_fill_price = round(max(market_price, ask), 6)
            expected_slippage = round(max(expected_fill_price - market_price, 0.0), 6)
            return ExecutionQualityDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                expected_fill_price=expected_fill_price,
                expected_slippage=expected_slippage,
                execution_quality_reason="spread_too_wide",
            )

        reduced = False
        if observed_spread >= self._config.borderline_execution_spread:
            size *= self._config.execution_reduction_factor
            reduced = True

        depth_key_present = any(
            key in context for key in ("orderbook_depth_usd", "depth_usd", "liquidity_usd")
        )
        depth_usd = float(
            context.get(
                "orderbook_depth_usd",
                context.get("depth_usd", context.get("liquidity_usd", 0.0)),
            )
        )
        if depth_usd < 0.0:
            depth_usd = 0.0

        if depth_key_present:
            if depth_usd < self._config.min_execution_depth_usd:
                return ExecutionQualityDecision(
                    final_decision="SKIP",
                    adjusted_size=0.0,
                    expected_fill_price=round(max(market_price, ask), 6),
                    expected_slippage=round(max(ask - market_price, 0.0), 6),
                    execution_quality_reason="insufficient_depth",
                )
            if depth_usd < self._config.borderline_execution_depth_usd:
                size *= self._config.execution_reduction_factor
                reduced = True
            if size > depth_usd * self._config.max_position_size_ratio:
                size = depth_usd * self._config.max_position_size_ratio
                reduced = True

        if 0.0 < size < self._config.min_position_size_usd:
            return ExecutionQualityDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                expected_fill_price=round(max(market_price, ask), 6),
                expected_slippage=round(max(ask - market_price, 0.0), 6),
                execution_quality_reason="insufficient_depth",
            )

        depth_denominator = max(depth_usd, 1.0) if depth_key_present else max(size, 1.0)
        market_impact = (size / depth_denominator) * 0.01
        half_spread = observed_spread / 2.0
        expected_slippage = max(0.0, half_spread + market_impact)
        expected_fill_price = min(1.0, max(market_price, ask) + expected_slippage)
        safe_signal_edge = max(signal_edge, 0.0)

        if (
            safe_signal_edge <= 0.0
            or expected_slippage >= safe_signal_edge
            or expected_slippage >= (safe_signal_edge * self._config.max_slippage_edge_consumption_ratio)
        ):
            return ExecutionQualityDecision(
                final_decision="SKIP",
                adjusted_size=0.0,
                expected_fill_price=round(expected_fill_price, 6),
                expected_slippage=round(expected_slippage, 6),
                execution_quality_reason="slippage_too_high",
            )

        if (
            not reduced
            and expected_slippage
            >= (safe_signal_edge * self._config.borderline_slippage_edge_consumption_ratio)
        ):
            size *= self._config.execution_reduction_factor
            reduced = True
            depth_denominator = max(depth_usd, 1.0) if depth_key_present else max(size, 1.0)
            market_impact = (size / depth_denominator) * 0.01
            expected_slippage = max(0.0, half_spread + market_impact)
            expected_fill_price = min(1.0, max(market_price, ask) + expected_slippage)

        decision = "REDUCE" if reduced and size < proposed_size else "ENTER"
        reason = "size_reduced_for_liquidity" if decision == "REDUCE" else "fill_quality_ok"
        return ExecutionQualityDecision(
            final_decision=decision,
            adjusted_size=round(max(size, 0.0), 2),
            expected_fill_price=round(expected_fill_price, 6),
            expected_slippage=round(expected_slippage, 6),
            execution_quality_reason=reason,
        )

    def evaluate_entry_timing(
        self,
        *,
        market_price: float,
        signal_reference_price: float,
        signal_edge: float,
        market_context: dict[str, float] | None = None,
        wait_cycles: int = 0,
    ) -> EntryTimingDecision:
        context = market_context or {}
        normalized_wait_cycles = max(wait_cycles, 0)
        reference_price = signal_reference_price if signal_reference_price > 0.0 else market_price
        reference_price = max(reference_price, 0.0)
        reevaluation_window = max(self._config.timing_reevaluation_window_seconds, 1)

        bid = float(context.get("best_bid", market_price))
        ask = float(context.get("best_ask", market_price))
        spread = max(0.0, ask - bid)

        if reference_price <= 0.0:
            return EntryTimingDecision(
                timing_decision="SKIP",
                timing_reason="invalid_reference_price",
                reference_price=0.0,
                reevaluation_window=reevaluation_window,
                final_execution_readiness=False,
            )

        extension_ratio = max((market_price - reference_price) / reference_price, 0.0)
        spread_ratio = spread / max(reference_price, 1e-6)
        post_signal_peak = max(float(context.get("post_signal_peak_price", market_price)), market_price)
        pullback_from_peak = max((post_signal_peak - market_price) / max(post_signal_peak, 1e-6), 0.0)

        chase_detected = (
            extension_ratio >= self._config.anti_chase_extension_ratio
            and spread_ratio >= self._config.anti_chase_spread_ratio
        )
        if chase_detected:
            if normalized_wait_cycles >= self._config.timing_max_wait_cycles:
                return EntryTimingDecision(
                    timing_decision="SKIP",
                    timing_reason="anti_chase_timeout_skip",
                    reference_price=round(reference_price, 6),
                    reevaluation_window=0,
                    final_execution_readiness=False,
                )
            return EntryTimingDecision(
                timing_decision="WAIT",
                timing_reason="anti_chase_spike_detected",
                reference_price=round(reference_price, 6),
                reevaluation_window=reevaluation_window,
                final_execution_readiness=False,
            )

        if post_signal_peak > reference_price * (1.0 + (self._config.anti_chase_extension_ratio / 2.0)):
            if pullback_from_peak >= self._config.micro_pullback_improvement_ratio:
                return EntryTimingDecision(
                    timing_decision="ENTER_NOW",
                    timing_reason="micro_pullback_improved_entry",
                    reference_price=round(reference_price, 6),
                    reevaluation_window=0,
                    final_execution_readiness=True,
                )
            if normalized_wait_cycles >= self._config.timing_max_wait_cycles:
                return EntryTimingDecision(
                    timing_decision="SKIP",
                    timing_reason="micro_pullback_timeout_skip",
                    reference_price=round(reference_price, 6),
                    reevaluation_window=0,
                    final_execution_readiness=False,
                )
            return EntryTimingDecision(
                timing_decision="WAIT",
                timing_reason="awaiting_micro_pullback",
                reference_price=round(reference_price, 6),
                reevaluation_window=reevaluation_window,
                final_execution_readiness=False,
            )

        if signal_edge <= 0.0:
            return EntryTimingDecision(
                timing_decision="ENTER_NOW",
                timing_reason="timing_unclear_fallback_to_quality_gate",
                reference_price=round(reference_price, 6),
                reevaluation_window=0,
                final_execution_readiness=True,
            )

        return EntryTimingDecision(
            timing_decision="ENTER_NOW",
            timing_reason="stable_entry_window",
            reference_price=round(reference_price, 6),
            reevaluation_window=0,
            final_execution_readiness=True,
        )

    def evaluate_entry_execution_readiness(
        self,
        *,
        market_price: float,
        signal_reference_price: float,
        proposed_size: float,
        signal_edge: float,
        market_context: dict[str, float] | None = None,
        wait_cycles: int = 0,
    ) -> EntryExecutionReadiness:
        timing = self.evaluate_entry_timing(
            market_price=market_price,
            signal_reference_price=signal_reference_price,
            signal_edge=signal_edge,
            market_context=market_context,
            wait_cycles=wait_cycles,
        )
        if timing.timing_decision != "ENTER_NOW":
            return EntryExecutionReadiness(
                timing_decision=timing.timing_decision,
                timing_reason=timing.timing_reason,
                reference_price=timing.reference_price,
                reevaluation_window=timing.reevaluation_window,
                final_execution_readiness=False,
                execution_quality_decision="NOT_EVALUATED",
                execution_quality_reason="timing_gate_blocked",
                adjusted_size=0.0,
                expected_fill_price=round(max(market_price, 0.0), 6),
                expected_slippage=0.0,
            )

        execution_quality = self.evaluate_execution_quality(
            market_price=market_price,
            proposed_size=proposed_size,
            signal_edge=signal_edge,
            market_context=market_context,
        )
        execution_ready = execution_quality.final_decision in {"ENTER", "REDUCE"}
        return EntryExecutionReadiness(
            timing_decision=timing.timing_decision,
            timing_reason=timing.timing_reason,
            reference_price=timing.reference_price,
            reevaluation_window=timing.reevaluation_window,
            final_execution_readiness=execution_ready,
            execution_quality_decision=execution_quality.final_decision,
            execution_quality_reason=execution_quality.execution_quality_reason,
            adjusted_size=execution_quality.adjusted_size,
            expected_fill_price=execution_quality.expected_fill_price,
            expected_slippage=execution_quality.expected_slippage,
        )

    def evaluate_exit_decision(
        self,
        *,
        tracked_position: object,
        market_context: dict[str, float | str | bool] | None = None,
        aggregation_decision: StrategyAggregationDecision | None = None,
        now_ts: float | None = None,
    ) -> ExitDecision:
        context = market_context or {}
        current_time = time.time() if now_ts is None else now_ts
        created_at = float(getattr(tracked_position, "created_at", current_time))
        trade_duration = max(int(current_time - created_at), 0)
        current_pnl = float(getattr(tracked_position, "pnl", 0.0))
        entry_price = max(float(getattr(tracked_position, "entry_price", 0.0)), 1e-6)
        current_price = max(float(getattr(tracked_position, "current_price", entry_price)), 0.0)
        position_size = max(float(getattr(tracked_position, "size", 0.0)), 0.0)
        position_id = str(getattr(tracked_position, "position_id", ""))

        peak_pnl = max(self._position_peak_pnl.get(position_id, current_pnl), current_pnl)
        self._position_peak_pnl[position_id] = peak_pnl

        regime = (
            aggregation_decision.current_regime
            if aggregation_decision is not None
            else str(context.get("current_regime", "LOW_ACTIVITY_CHAOTIC"))
        )
        adaptive_state = self.get_adaptive_adjustment_state()
        avg_weight = (
            sum(adaptive_state.strategy_weights.values()) / len(adaptive_state.strategy_weights)
            if adaptive_state.strategy_weights
            else 1.0
        )

        regime_factor = 1.0
        if regime == "LOW_ACTIVITY_CHAOTIC":
            regime_factor *= self._config.fast_exit_regime_factor
        elif regime in {"NEWS_DRIVEN", "SMART_MONEY_DOMINANT"}:
            regime_factor *= self._config.slow_exit_regime_factor

        if avg_weight < 0.98:
            regime_factor *= 0.9
        elif avg_weight > 1.02:
            regime_factor *= 1.1

        bounded_factor = self._clamp(regime_factor, 0.65, 1.35)
        stop_loss_limit = position_size * self._config.stop_loss_ratio * bounded_factor
        favorable_threshold = max(
            self._config.target_pnl * bounded_factor,
            position_size * self._config.favorable_pnl_ratio * bounded_factor,
        )
        effective_max_duration = max(int(self._config.max_trade_duration_seconds * bounded_factor), 60)
        effective_hard_max_duration = max(
            int(self._config.hard_max_trade_duration_seconds * bounded_factor),
            effective_max_duration,
        )
        stale_move_ratio = self._config.stale_trade_price_move_ratio * bounded_factor
        price_move_ratio = abs(current_price - entry_price) / entry_price

        if bool(context.get("signal_invalidated", False)):
            return ExitDecision(
                exit_decision="EXIT_FULL",
                exit_reason="signal_invalidation",
                pnl_snapshot=round(current_pnl, 6),
                trade_duration=trade_duration,
            )

        if current_pnl <= -abs(stop_loss_limit):
            return ExitDecision(
                exit_decision="EXIT_FULL",
                exit_reason="stop_loss_threshold_breached",
                pnl_snapshot=round(current_pnl, 6),
                trade_duration=trade_duration,
            )

        if trade_duration >= effective_hard_max_duration:
            return ExitDecision(
                exit_decision="EXIT_FULL",
                exit_reason="max_duration_guard",
                pnl_snapshot=round(current_pnl, 6),
                trade_duration=trade_duration,
            )

        if trade_duration >= effective_max_duration and price_move_ratio <= stale_move_ratio:
            return ExitDecision(
                exit_decision="EXIT_FULL",
                exit_reason="stale_trade_timeout",
                pnl_snapshot=round(current_pnl, 6),
                trade_duration=trade_duration,
            )

        if peak_pnl >= favorable_threshold:
            pullback_from_peak = peak_pnl - current_pnl
            weakening_threshold = peak_pnl * self._config.momentum_weakening_ratio
            if pullback_from_peak >= weakening_threshold:
                return ExitDecision(
                    exit_decision="EXIT_FULL",
                    exit_reason="momentum_weakened_after_favorable_move",
                    pnl_snapshot=round(current_pnl, 6),
                    trade_duration=trade_duration,
                )
            return ExitDecision(
                exit_decision="HOLD",
                exit_reason="favorable_momentum_intact",
                pnl_snapshot=round(current_pnl, 6),
                trade_duration=trade_duration,
            )

        return ExitDecision(
            exit_decision="HOLD",
            exit_reason="exit_conditions_not_met",
            pnl_snapshot=round(current_pnl, 6),
            trade_duration=trade_duration,
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

    def _select_best_settlement_gap_match(
        self,
        kalshi_market: KalshiResolvedMarket,
        polymarket_markets: list[PolymarketSettlementMarket],
    ) -> tuple[PolymarketSettlementMarket | None, float]:
        best_market: PolymarketSettlementMarket | None = None
        best_score = 0.0
        kalshi_tokens = set(self._tokenize(kalshi_market.title))

        for candidate in polymarket_markets:
            candidate_tokens = set(self._tokenize(candidate.title))
            overlap = len(kalshi_tokens & candidate_tokens)
            overlap_score = min(
                1.0,
                overlap / max(float(self._config.cross_exchange_min_overlap_tokens), 1.0),
            )
            event_match = 1.0 if kalshi_market.event_key and kalshi_market.event_key == candidate.event_key else 0.0
            timeframe_match = 1.0 if kalshi_market.timeframe and kalshi_market.timeframe == candidate.timeframe else 0.0
            resolution_match = (
                1.0
                if kalshi_market.resolution_criteria
                and kalshi_market.resolution_criteria == candidate.resolution_criteria
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
        market_context: dict[str, float] | None = None,
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
            selected_candidate = None
            if aggregation_decision is not None and aggregation_decision.selected_trade:
                selected_candidate = next(
                    (
                        item
                        for item in aggregation_decision.ranked_candidates
                        if item.strategy_name == aggregation_decision.selected_trade
                    ),
                    None,
                )
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
            target_market_id, target_theme = self._resolve_candidate_market_context(selected_candidate)
            portfolio_guard = self.evaluate_portfolio_exposure_and_correlation(
                target_market_id=target_market_id,
                target_theme=target_theme,
                proposed_size=sizing.position_size,
                open_positions=list(snapshot.positions),
                total_capital=snapshot.equity,
            )
            if portfolio_guard.final_decision == "SKIP":
                return "BLOCKED"
            signal_edge = max(self._config.min_edge, 0.0)
            if selected_candidate is not None:
                signal_edge = max(selected_candidate.edge, 0.0)
            timing_wait_cycles = int((market_context or {}).get("timing_wait_cycles", 0.0))
            signal_reference_price = float((market_context or {}).get("signal_reference_price", market_price))
            readiness = self.evaluate_entry_execution_readiness(
                market_price=market_price,
                signal_reference_price=signal_reference_price,
                proposed_size=portfolio_guard.adjusted_size,
                signal_edge=signal_edge,
                market_context=market_context,
                wait_cycles=timing_wait_cycles,
            )
            if readiness.timing_decision == "WAIT":
                log.info(
                    "entry_timing_wait",
                    timing_reason=readiness.timing_reason,
                    reference_price=readiness.reference_price,
                    reevaluation_window=readiness.reevaluation_window,
                )
                return "HOLD"
            if readiness.timing_decision == "SKIP":
                log.info(
                    "entry_timing_skip",
                    timing_reason=readiness.timing_reason,
                    reference_price=readiness.reference_price,
                )
                return "BLOCKED"
            if not readiness.final_execution_readiness:
                log.info(
                    "execution_quality_blocked",
                    reason=readiness.execution_quality_reason,
                    expected_fill_price=readiness.expected_fill_price,
                    expected_slippage=readiness.expected_slippage,
                )
                return "BLOCKED"
            size = readiness.adjusted_size
            candidate_title = (
                selected_candidate.title
                if selected_candidate is not None and selected_candidate.title
                else target_market_id
            )
            created = await self._engine.open_position(
                market=target_market_id,
                market_title=str(candidate_title),
                side=self._config.side,
                price=readiness.expected_fill_price,
                size=size,
                position_id=str(uuid.uuid4()),
                position_context={
                    "strategy_source": (
                        selected_candidate.strategy_name
                        if selected_candidate is not None
                        else "UNKNOWN"
                    ),
                    "regime_at_entry": (
                        aggregation_decision.current_regime
                        if aggregation_decision is not None
                        else str((market_context or {}).get("current_regime", "LOW_ACTIVITY_CHAOTIC"))
                    ),
                    "entry_quality": readiness.execution_quality_reason,
                    "entry_timing": readiness.timing_reason,
                    "theoretical_edge": signal_edge,
                    "slippage_impact": readiness.expected_slippage,
                    "timing_effectiveness": 1.0 if readiness.timing_decision == "ENTER_NOW" else 0.0,
                },
            )
            if created:
                self._position_entry_context[created.position_id] = {
                    "strategy_source": (
                        selected_candidate.strategy_name
                        if selected_candidate is not None
                        else "UNKNOWN"
                    ),
                    "regime_at_entry": (
                        aggregation_decision.current_regime
                        if aggregation_decision is not None
                        else str((market_context or {}).get("current_regime", "LOW_ACTIVITY_CHAOTIC"))
                    ),
                    "entry_quality": readiness.execution_quality_reason,
                    "entry_timing": readiness.timing_reason,
                    "theoretical_edge": signal_edge,
                    "slippage_impact": readiness.expected_slippage,
                    "timing_effectiveness": 1.0 if readiness.timing_decision == "ENTER_NOW" else 0.0,
                }
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
            if tracked is not None:
                exit_decision = self.evaluate_exit_decision(
                    tracked_position=tracked,
                    market_context=market_context,
                    aggregation_decision=aggregation_decision,
                )
                if exit_decision.exit_decision == "HOLD":
                    return "HOLD"
                entry_context = self._position_entry_context.pop(tracked.position_id, {})
                exit_efficiency = 0.5
                if exit_decision.exit_reason == "momentum_weakened_after_favorable_move":
                    exit_efficiency = 1.0
                elif exit_decision.exit_reason in {"stop_loss_threshold_breached", "signal_invalidation"}:
                    exit_efficiency = 0.3
                await self._engine.close_position(
                    tracked,
                    market_price,
                    close_context={
                        **entry_context,
                        "exit_reason": exit_decision.exit_reason,
                        "exit_efficiency": exit_efficiency,
                    },
                )
                self._position_peak_pnl.pop(str(getattr(tracked, "position_id", "")), None)
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
