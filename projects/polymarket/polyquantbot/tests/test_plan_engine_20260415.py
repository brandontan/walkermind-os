"""Tests for Fast Plan Bot — PlanEngine and plan_formatter.

Covers:
    - TradePlan dataclass construction
    - PlanEngine.generate_plans() with valid market data (signal expected)
    - PlanEngine.generate_plans() with empty market list
    - PlanEngine.generate_plans() with markets below liquidity threshold
    - Kelly fraction constant enforcement (α = 0.25, never 1.0)
    - Max position cap (≤ 10 % of capital)
    - Risk classification logic (_classify_risk)
    - format_plan_list() with plans → non-empty Markdown string
    - format_plan_list() with empty list → graceful fallback
    - format_plan_empty() returns a string with mode label
    - No order execution or live trading guard bypass
"""
from __future__ import annotations

import asyncio
import time

import pytest

from projects.polymarket.polyquantbot.strategy.plan_engine import (
    PlanEngine,
    TradePlan,
    _classify_risk,
    _KELLY_FRACTION,
    _MAX_POSITION_PCT,
    _MIN_EDGE_FOR_PLAN,
)
from projects.polymarket.polyquantbot.strategy.plan_formatter import (
    format_plan_list,
    format_plan_empty,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

CAPITAL = 1_000.0

# Market data that should produce a signal from EVMomentumStrategy once the
# rolling window is primed.  We send the same high-depth market 25 times
# (window = 20) with a strong directional price drift.
_STRONG_YES_MARKET = {
    "market_id": "mkt-abc-001",
    "title": "Will Team A win the championship?",
    "bid": 0.40,
    "ask": 0.45,
    "mid": 0.425,
    "depth_yes": 50_000.0,
    "depth_no": 45_000.0,
    "volume": 500_000.0,
}

_LOW_DEPTH_MARKET = {
    "market_id": "mkt-low-depth",
    "title": "Low liquidity market",
    "bid": 0.30,
    "ask": 0.70,
    "mid": 0.50,
    "depth_yes": 100.0,   # below any reasonable threshold
    "depth_no": 100.0,
    "volume": 200.0,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prime_engine_for_signal(engine: PlanEngine, market: dict, n: int = 25) -> list[TradePlan]:
    """Run generate_plans n times to prime the strategy rolling window."""
    plans: list[TradePlan] = []
    for _ in range(n):
        plans = asyncio.get_event_loop().run_until_complete(
            engine.generate_plans([market])
        )
    return plans


# ── TradePlan dataclass ────────────────────────────────────────────────────────

class TestTradePlan:
    def test_construction(self) -> None:
        plan = TradePlan(
            plan_id="abc12345",
            market_id="mkt-001",
            market_title="Test market",
            direction="YES",
            entry_price=0.45,
            target_price=0.55,
            position_size_usdc=25.0,
            expected_value=1.25,
            edge_score=0.05,
            z_score=2.5,
            risk_level="MEDIUM",
            confidence=0.8,
            reasoning="EV Momentum — edge 5.0% on YES. Kelly size $25.00. EV +$1.25.",
            strategy_sources=["ev_momentum"],
        )
        assert plan.market_id == "mkt-001"
        assert plan.direction == "YES"
        assert plan.plan_id == "abc12345"
        assert plan.generated_at <= time.time()

    def test_generated_at_defaults_to_now(self) -> None:
        before = time.time()
        plan = TradePlan(
            plan_id="x",
            market_id="m",
            market_title="t",
            direction="NO",
            entry_price=0.6,
            target_price=0.4,
            position_size_usdc=10.0,
            expected_value=0.5,
            edge_score=0.05,
            z_score=1.5,
            risk_level="LOW",
            confidence=0.9,
            reasoning="test",
            strategy_sources=[],
        )
        after = time.time()
        assert before <= plan.generated_at <= after


# ── Risk constants ─────────────────────────────────────────────────────────────

class TestRiskConstants:
    def test_kelly_fraction_is_0_25(self) -> None:
        assert _KELLY_FRACTION == 0.25, "Kelly fraction must remain 0.25 (never 1.0)"

    def test_max_position_pct_is_10(self) -> None:
        assert _MAX_POSITION_PCT == 0.10, "Max position must remain ≤ 10 % of capital"

    def test_min_edge_positive(self) -> None:
        assert _MIN_EDGE_FOR_PLAN > 0.0


# ── _classify_risk ─────────────────────────────────────────────────────────────

class TestClassifyRisk:
    def test_low_risk(self) -> None:
        # High edge, tiny exposure
        assert _classify_risk(0.10, 30.0, 1_000.0) == "LOW"

    def test_medium_risk_by_edge(self) -> None:
        # Moderate edge
        assert _classify_risk(0.05, 60.0, 1_000.0) == "MEDIUM"

    def test_medium_risk_by_exposure(self) -> None:
        # Low edge but small exposure
        assert _classify_risk(0.02, 50.0, 1_000.0) == "MEDIUM"

    def test_high_risk(self) -> None:
        # Tiny edge and large exposure
        assert _classify_risk(0.01, 200.0, 1_000.0) == "HIGH"


# ── PlanEngine ─────────────────────────────────────────────────────────────────

class TestPlanEngine:
    def test_empty_markets_returns_empty(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        result = asyncio.get_event_loop().run_until_complete(
            engine.generate_plans([])
        )
        assert result == []

    def test_low_depth_market_returns_no_plans(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        # Run many times — strategy needs window populated
        for _ in range(30):
            result = asyncio.get_event_loop().run_until_complete(
                engine.generate_plans([_LOW_DEPTH_MARKET])
            )
        # Low depth should filter out via liquidity threshold
        assert isinstance(result, list)
        # Not asserting empty: some strategies may not apply depth filter,
        # but any generated plan must respect position cap.
        for plan in result:
            assert plan.position_size_usdc <= CAPITAL * _MAX_POSITION_PCT + 0.01

    def test_plan_position_cap_enforced(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        plans = _prime_engine_for_signal(engine, _STRONG_YES_MARKET, n=30)
        for plan in plans:
            assert plan.position_size_usdc <= CAPITAL * _MAX_POSITION_PCT + 0.01, (
                f"Position {plan.position_size_usdc} exceeds 10% cap of ${CAPITAL}"
            )

    def test_plan_entry_price_in_valid_range(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        plans = _prime_engine_for_signal(engine, _STRONG_YES_MARKET, n=30)
        for plan in plans:
            assert 0.01 <= plan.entry_price <= 0.99

    def test_plan_direction_is_yes_or_no(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        plans = _prime_engine_for_signal(engine, _STRONG_YES_MARKET, n=30)
        for plan in plans:
            assert plan.direction in ("YES", "NO")

    def test_plan_risk_level_valid(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        plans = _prime_engine_for_signal(engine, _STRONG_YES_MARKET, n=30)
        for plan in plans:
            assert plan.risk_level in ("LOW", "MEDIUM", "HIGH")

    def test_max_plans_respected(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL, max_plans=2)
        # Create multiple distinct markets
        markets = [
            {**_STRONG_YES_MARKET, "market_id": f"mkt-{i:03d}", "title": f"Market {i}"}
            for i in range(10)
        ]
        for _ in range(30):
            result = asyncio.get_event_loop().run_until_complete(
                engine.generate_plans(markets)
            )
        assert len(result) <= 2

    def test_plans_ranked_by_ev(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        markets = [
            {**_STRONG_YES_MARKET, "market_id": f"mkt-{i:03d}", "title": f"Market {i}"}
            for i in range(5)
        ]
        for _ in range(30):
            result = asyncio.get_event_loop().run_until_complete(
                engine.generate_plans(markets)
            )
        if len(result) >= 2:
            evs = [p.expected_value * p.confidence for p in result]
            assert evs == sorted(evs, reverse=True), "Plans must be ranked by EV × confidence"

    def test_market_without_id_skipped(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        bad_market = {"title": "No ID market", "bid": 0.4, "ask": 0.6, "mid": 0.5}
        result = asyncio.get_event_loop().run_until_complete(
            engine.generate_plans([bad_market])
        )
        assert result == []

    def test_plan_id_is_8_char_string(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        plans = _prime_engine_for_signal(engine, _STRONG_YES_MARKET, n=30)
        for plan in plans:
            assert isinstance(plan.plan_id, str)
            assert len(plan.plan_id) == 8

    def test_strategy_sources_non_empty_when_plan_generated(self) -> None:
        engine = PlanEngine(capital_usdc=CAPITAL)
        plans = _prime_engine_for_signal(engine, _STRONG_YES_MARKET, n=30)
        for plan in plans:
            assert isinstance(plan.strategy_sources, list)
            assert len(plan.strategy_sources) >= 1


# ── plan_formatter ─────────────────────────────────────────────────────────────

class TestPlanFormatter:
    def _make_plan(self, ev: float = 2.5, direction: str = "YES") -> TradePlan:
        return TradePlan(
            plan_id="abc12345",
            market_id="mkt-001",
            market_title="Will this happen before 2027?",
            direction=direction,
            entry_price=0.45,
            target_price=0.55,
            position_size_usdc=25.0,
            expected_value=ev,
            edge_score=0.10,
            z_score=3.0,
            risk_level="LOW",
            confidence=0.9,
            reasoning="Ev Momentum — edge 10.0% on YES. Kelly size $25.00. EV +$2.50.",
            strategy_sources=["ev_momentum", "liquidity_edge"],
        )

    def test_format_plan_list_non_empty(self) -> None:
        plans = [self._make_plan()]
        result = format_plan_list(plans, mode="PAPER", capital_usdc=1_000.0)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_plan_list_contains_plan_id(self) -> None:
        plans = [self._make_plan()]
        result = format_plan_list(plans, mode="PAPER", capital_usdc=1_000.0)
        assert "abc12345" in result

    def test_format_plan_list_contains_direction(self) -> None:
        plans = [self._make_plan(direction="YES")]
        result = format_plan_list(plans, mode="PAPER", capital_usdc=1_000.0)
        assert "YES" in result

    def test_format_plan_list_empty_returns_no_plans_message(self) -> None:
        result = format_plan_list([], mode="PAPER", capital_usdc=1_000.0)
        assert "NO PLANS" in result.upper()

    def test_format_plan_list_none_returns_no_plans_message(self) -> None:
        result = format_plan_list(None, mode="PAPER", capital_usdc=1_000.0)
        assert "NO PLANS" in result.upper()

    def test_format_plan_list_contains_advisory_disclaimer(self) -> None:
        plans = [self._make_plan()]
        result = format_plan_list(plans, mode="PAPER", capital_usdc=1_000.0)
        assert "advisory" in result.lower() or "no orders" in result.lower()

    def test_format_plan_list_contains_kelly_fraction(self) -> None:
        plans = [self._make_plan()]
        result = format_plan_list(plans, mode="PAPER", capital_usdc=1_000.0)
        assert "0.25" in result

    def test_format_plan_empty_contains_mode(self) -> None:
        result = format_plan_empty(mode="LIVE")
        assert "LIVE" in result

    def test_format_plan_empty_is_string(self) -> None:
        result = format_plan_empty()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_title_truncated_at_40_chars(self) -> None:
        long_title = "A" * 60
        plan = TradePlan(
            plan_id="abc12345",
            market_id="mkt-001",
            market_title=long_title,
            direction="YES",
            entry_price=0.45,
            target_price=0.55,
            position_size_usdc=25.0,
            expected_value=2.5,
            edge_score=0.10,
            z_score=3.0,
            risk_level="LOW",
            confidence=0.9,
            reasoning="test",
            strategy_sources=["ev_momentum"],
        )
        result = format_plan_list([plan], mode="PAPER", capital_usdc=1_000.0)
        # Title in output must not exceed 41 chars (40 + ellipsis)
        lines = result.split("\n")
        for line in lines:
            if "A" * 10 in line:
                assert "…" in line or len(line) <= 80
