"""strategy.plan_engine — Fast Plan Bot core planning engine.

Generates ranked TradePlan objects from a list of market candidates by
evaluating them across all registered strategies and applying
Kelly-constrained (α = 0.25) position sizing.

Design:
    - Stateless per call: no side effects, no order placement.
    - Uses existing strategy implementations (EVMomentum, LiquidityEdge,
      MeanReversion) — no new strategy logic introduced.
    - Kelly α = 0.25 enforced; α = 1.0 is FORBIDDEN.
    - Max position = 10 % of capital per plan.
    - Plans are read-only advisory output.
    - ENABLE_LIVE_TRADING is NOT touched by this module.

Risk constants (FIXED — never change):
    KELLY_FRACTION     = 0.25
    MAX_POSITION_PCT   = 0.10
    MIN_EDGE_FOR_PLAN  = 0.02
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from .base.base_strategy import SignalResult
from .implementations.ev_momentum import EVMomentumStrategy
from .implementations.liquidity_edge import LiquidityEdgeStrategy
from .implementations.mean_reversion import MeanReversionStrategy

log = structlog.get_logger(__name__)

# ── Risk Constants (FIXED) ─────────────────────────────────────────────────────

_KELLY_FRACTION: float = 0.25         # fractional Kelly — never 1.0
_MAX_POSITION_PCT: float = 0.10       # max 10 % of capital
_MIN_EDGE_FOR_PLAN: float = 0.02      # minimum edge to include a plan
_DEFAULT_CAPITAL_USDC: float = 1_000.0
_MAX_PLANS: int = 5


# ── TradePlan ──────────────────────────────────────────────────────────────────


@dataclass
class TradePlan:
    """Structured trade recommendation produced by PlanEngine.

    Attributes:
        plan_id:            Short unique ID (first 8 chars of UUID4).
        market_id:          Polymarket condition ID.
        market_title:       Human-readable market question / title.
        direction:          Trade direction — "YES" or "NO".
        entry_price:        Recommended entry price (0–1 range).
        target_price:       Price target based on projected edge resolution.
        position_size_usdc: Recommended position size in USDC (Kelly-capped).
        expected_value:     Estimated dollar EV = edge × position_size_usdc.
        edge_score:         Raw strategy edge (p_model − p_market equivalent).
        z_score:            Approximated signal strength relative to noise.
        risk_level:         "LOW" | "MEDIUM" | "HIGH".
        confidence:         Aggregated confidence across contributing signals (0–1).
        reasoning:          Single-sentence human-readable plan rationale.
        strategy_sources:   Names of strategies that contributed signals.
        generated_at:       UNIX timestamp of plan generation.
    """

    plan_id: str
    market_id: str
    market_title: str
    direction: str
    entry_price: float
    target_price: float
    position_size_usdc: float
    expected_value: float
    edge_score: float
    z_score: float
    risk_level: str
    confidence: float
    reasoning: str
    strategy_sources: List[str]
    generated_at: float = field(default_factory=time.time)


# ── PlanEngine ─────────────────────────────────────────────────────────────────


class PlanEngine:
    """Fast Plan Bot planning engine.

    Evaluates a list of market candidates using all registered strategies,
    applies risk constraints, and returns a ranked list of TradePlan objects.

    Args:
        capital_usdc:   Total available capital for position sizing (USDC).
        min_edge:       Minimum strategy edge required to include a plan.
        max_plans:      Maximum number of plans to return (default 5).
    """

    def __init__(
        self,
        capital_usdc: float = _DEFAULT_CAPITAL_USDC,
        min_edge: float = _MIN_EDGE_FOR_PLAN,
        max_plans: int = _MAX_PLANS,
    ) -> None:
        self._capital_usdc = max(1.0, capital_usdc)
        self._min_edge = min_edge
        self._max_plans = max_plans
        self._strategies = [
            EVMomentumStrategy(min_edge=min_edge),
            LiquidityEdgeStrategy(min_edge=min_edge),
            MeanReversionStrategy(min_edge=min_edge),
        ]
        log.info(
            "plan_engine_initialized",
            capital_usdc=self._capital_usdc,
            min_edge=self._min_edge,
            max_plans=self._max_plans,
            strategies=[s.name for s in self._strategies],
        )

    async def generate_plans(
        self,
        markets: List[Dict[str, Any]],
    ) -> List[TradePlan]:
        """Evaluate market candidates and return ranked trade plans.

        Evaluates each market across all registered strategies, aggregates
        signals, applies Kelly sizing, classifies risk, and returns up to
        ``max_plans`` plans ranked by expected_value × confidence.

        Args:
            markets: List of market dicts.  Expected keys per market:
                     market_id (str), title (str), bid (float), ask (float),
                     mid (float), depth_yes (float), depth_no (float),
                     volume (float).  Missing keys default to safe values.

        Returns:
            Ranked list of TradePlan objects (highest EV first).
        """
        if not markets:
            log.info("plan_engine_no_markets")
            return []

        plans: List[TradePlan] = []
        for market in markets:
            try:
                plan = await self._evaluate_market(market)
                if plan is not None:
                    plans.append(plan)
            except Exception as exc:
                market_id = str(market.get("market_id", "unknown"))
                log.error(
                    "plan_engine.market_eval_error",
                    market_id=market_id,
                    error=str(exc),
                )

        plans.sort(key=lambda p: p.expected_value * p.confidence, reverse=True)

        result = plans[: self._max_plans]
        log.info(
            "plan_engine_plans_generated",
            candidates=len(markets),
            plans=len(result),
        )
        return result

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _evaluate_market(
        self,
        market: Dict[str, Any],
    ) -> Optional[TradePlan]:
        """Evaluate a single market across all strategies.

        Returns the highest-edge plan for this market or None if no
        signal meets the minimum edge threshold.
        """
        market_id: str = str(market.get("market_id", ""))
        market_title: str = str(market.get("title", market_id))

        if not market_id:
            return None

        signals: List[SignalResult] = []
        strategy_names: List[str] = []

        for strategy in self._strategies:
            try:
                result = await strategy.evaluate(market_id, market)
                if result is not None and result.edge >= self._min_edge:
                    signals.append(result)
                    strategy_names.append(strategy.name)
            except Exception as exc:
                log.warning(
                    "plan_engine.strategy_error",
                    strategy=strategy.name,
                    market_id=market_id,
                    error=str(exc),
                )

        if not signals:
            return None

        # Best signal by edge
        best: SignalResult = max(signals, key=lambda s: s.edge)
        agg_confidence: float = min(
            1.0, sum(s.confidence for s in signals) / max(1, len(signals))
        )

        # Price references
        bid: float = float(market.get("bid", 0.0))
        ask: float = float(market.get("ask", 1.0))
        entry_price: float = ask if best.side == "YES" else bid
        entry_price = max(0.01, min(0.99, entry_price))

        # Kelly-constrained size: f = (edge / (1/p)) × α, capped at 10 % capital
        p: float = max(entry_price, 1e-6)
        kelly_raw: float = (best.edge / (1.0 / p)) * _KELLY_FRACTION * self._capital_usdc
        cap_max: float = self._capital_usdc * _MAX_POSITION_PCT
        position_size: float = round(max(1.0, min(kelly_raw, cap_max, best.size_usdc)), 2)

        # Expected value
        expected_value: float = round(best.edge * position_size, 4)

        # Target price: project edge distance toward resolution
        if best.side == "YES":
            target_price = round(min(entry_price + best.edge * 2.0, 0.99), 4)
        else:
            target_price = round(max(entry_price - best.edge * 2.0, 0.01), 4)

        # Z-score approximation
        noise_floor: float = max(0.005, 1.0 - agg_confidence)
        z_score: float = round(best.edge / noise_floor, 2)

        risk_level: str = _classify_risk(best.edge, position_size, self._capital_usdc)

        # Human-readable reasoning
        src_label = " + ".join(s.replace("_", " ").title() for s in strategy_names)
        reasoning = (
            f"{src_label} — edge {best.edge:.1%} on {best.side}. "
            f"Kelly size ${position_size:.2f}. EV +${expected_value:.2f}."
        )

        plan = TradePlan(
            plan_id=str(uuid.uuid4())[:8],
            market_id=market_id,
            market_title=market_title,
            direction=best.side,
            entry_price=round(entry_price, 4),
            target_price=target_price,
            position_size_usdc=position_size,
            expected_value=expected_value,
            edge_score=round(best.edge, 4),
            z_score=z_score,
            risk_level=risk_level,
            confidence=round(agg_confidence, 3),
            reasoning=reasoning,
            strategy_sources=strategy_names,
        )

        log.info(
            "plan_engine.plan_created",
            plan_id=plan.plan_id,
            market_id=market_id,
            direction=plan.direction,
            edge=plan.edge_score,
            ev=plan.expected_value,
            risk=plan.risk_level,
        )
        return plan


# ── Helpers ────────────────────────────────────────────────────────────────────


def _classify_risk(edge: float, size_usdc: float, capital_usdc: float) -> str:
    """Classify plan risk level from edge strength and capital exposure."""
    exposure: float = size_usdc / max(capital_usdc, 1.0)
    if edge >= 0.08 and exposure <= 0.05:
        return "LOW"
    if edge >= 0.04 or exposure <= 0.08:
        return "MEDIUM"
    return "HIGH"
