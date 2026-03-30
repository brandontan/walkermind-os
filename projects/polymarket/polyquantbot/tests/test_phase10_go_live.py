"""Phase 10 — Test suite for GO-LIVE Controller, Execution Guard,
Kalshi Client, and Arbitrage Detector.

Covers:
  TC-01  GoLiveController — blocked in PAPER mode
  TC-02  GoLiveController — blocked when metrics not set
  TC-03  GoLiveController — blocked when ev_capture below threshold
  TC-04  GoLiveController — blocked when fill_rate below threshold
  TC-05  GoLiveController — blocked when p95 latency exceeded
  TC-06  GoLiveController — blocked when drawdown exceeded
  TC-07  GoLiveController — allowed when all conditions pass
  TC-08  GoLiveController — daily trade cap blocks execution
  TC-09  GoLiveController — capital cap blocks execution
  TC-10  GoLiveController — from_config factory
  TC-11  GoLiveController — set_metrics from MetricsResult
  TC-12  ExecutionGuard — rejects on low liquidity
  TC-13  ExecutionGuard — rejects on high slippage
  TC-14  ExecutionGuard — rejects on large position
  TC-15  ExecutionGuard — rejects on duplicate signature
  TC-16  ExecutionGuard — passes all checks
  TC-17  ExecutionGuard — from_config factory
  TC-18  KalshiClient — _cents_to_probability edge cases
  TC-19  KalshiClient — _normalise_timestamp various formats
  TC-20  KalshiClient — _map_outcome mapping
  TC-21  KalshiClient — _normalise_market dict
  TC-22  KalshiClient — _normalise_trade dict
  TC-23  KalshiClient — get_markets returns empty list on API failure
  TC-24  KalshiClient — get_trades returns empty list on API failure
  TC-25  ArbDetector — no signal when spread below threshold
  TC-26  ArbDetector — signal emitted when spread exceeds threshold
  TC-27  ArbDetector — BUY_POLY direction when poly price is lower
  TC-28  ArbDetector — BUY_KALSHI direction when kalshi price is lower
  TC-29  ArbDetector — empty inputs produce no signals
  TC-30  ArbDetector — exact market_map matching takes precedence
  TC-31  ArbDetector — fuzzy title matching
  TC-32  ArbDetector — bad market data skipped without crash
  TC-33  MetricsResult — go_live_ready field present and correct
  TC-34  MetricsResult — go_live_ready False when gate fails
"""
from __future__ import annotations

import time
from typing import Optional

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_passing_metrics(
    ev_capture_ratio: float = 0.80,
    fill_rate: float = 0.65,
    p95_latency: float = 400.0,
    drawdown: float = 0.05,
) -> object:
    """Return a duck-typed MetricsResult-like object with all gates passing."""
    class _FakeMetrics:
        pass

    m = _FakeMetrics()
    m.ev_capture_ratio = ev_capture_ratio
    m.fill_rate = fill_rate
    m.p95_latency = p95_latency
    m.drawdown = drawdown
    return m


# ══════════════════════════════════════════════════════════════════════════════
# TC-01 – TC-11  GoLiveController
# ══════════════════════════════════════════════════════════════════════════════

class TestGoLiveControllerPaperMode:
    """TC-01 — PAPER mode always blocks execution."""

    def test_paper_mode_blocks_execution(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController(mode=TradingMode.PAPER)
        ctrl.set_metrics(_make_passing_metrics())
        assert ctrl.allow_execution() is False

    def test_paper_mode_is_default(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController()
        assert ctrl.mode is TradingMode.PAPER


class TestGoLiveControllerMetricsNotSet:
    """TC-02 — LIVE mode with no metrics set blocks execution."""

    def test_live_no_metrics_blocked(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController(mode=TradingMode.LIVE)
        assert ctrl.allow_execution() is False


class TestGoLiveControllerMetricGates:
    """TC-03 – TC-07 — Individual metric gate failures and a full pass."""

    def _live_ctrl(self, **overrides) -> object:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode, GoLiveThresholds,
        )
        thresholds = GoLiveThresholds(
            ev_capture_min=0.75,
            fill_rate_min=0.60,
            p95_latency_max_ms=500.0,
            drawdown_max=0.08,
        )
        ctrl = GoLiveController(
            mode=TradingMode.LIVE,
            thresholds=thresholds,
            max_trades_per_day=1000,
        )
        ctrl.set_metrics(_make_passing_metrics(**overrides))
        return ctrl

    def test_ev_capture_below_threshold_blocked(self) -> None:
        ctrl = self._live_ctrl(ev_capture_ratio=0.50)  # below 0.75
        assert ctrl.allow_execution() is False

    def test_fill_rate_below_threshold_blocked(self) -> None:
        ctrl = self._live_ctrl(fill_rate=0.40)  # below 0.60
        assert ctrl.allow_execution() is False

    def test_p95_latency_exceeded_blocked(self) -> None:
        ctrl = self._live_ctrl(p95_latency=600.0)  # above 500ms
        assert ctrl.allow_execution() is False

    def test_drawdown_exceeded_blocked(self) -> None:
        ctrl = self._live_ctrl(drawdown=0.10)  # above 0.08
        assert ctrl.allow_execution() is False

    def test_all_gates_pass_allows_execution(self) -> None:
        ctrl = self._live_ctrl()  # all defaults pass
        assert ctrl.allow_execution() is True


class TestGoLiveControllerCaps:
    """TC-08 – TC-09 — Daily trade cap and capital cap."""

    def _ready_ctrl(self, max_trades: int = 5, max_capital: float = 1000.0):
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController(
            mode=TradingMode.LIVE,
            max_trades_per_day=max_trades,
            max_capital_usd=max_capital,
        )
        ctrl.set_metrics(_make_passing_metrics())
        return ctrl

    def test_daily_trade_cap_blocks(self) -> None:
        ctrl = self._ready_ctrl(max_trades=2)
        ctrl.record_trade(50.0)
        ctrl.record_trade(50.0)
        assert ctrl.allow_execution() is False

    def test_capital_cap_blocks(self) -> None:
        ctrl = self._ready_ctrl(max_capital=100.0)
        ctrl.record_trade(80.0)
        # Next trade would push to 80 + 30 = 110 > 100
        assert ctrl.allow_execution(trade_size_usd=30.0) is False

    def test_capital_cap_allows_exactly_at_limit(self) -> None:
        ctrl = self._ready_ctrl(max_capital=100.0)
        ctrl.record_trade(50.0)
        # 50 + 50 = 100 which is NOT > 100, so allowed
        assert ctrl.allow_execution(trade_size_usd=50.0) is True


class TestGoLiveControllerFactory:
    """TC-10 — from_config factory."""

    def test_from_config_live_mode(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        config = {
            "go_live": {
                "mode": "LIVE",
                "ev_capture_min": 0.70,
                "fill_rate_min": 0.55,
                "p95_latency_max_ms": 450.0,
                "drawdown_max": 0.07,
                "max_capital_usd": 5000.0,
                "max_trades_per_day": 100,
            }
        }
        ctrl = GoLiveController.from_config(config)
        assert ctrl.mode is TradingMode.LIVE
        assert ctrl._thresholds.ev_capture_min == pytest.approx(0.70)
        assert ctrl._max_capital_usd == pytest.approx(5000.0)

    def test_from_config_defaults_to_paper(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController.from_config({})
        assert ctrl.mode is TradingMode.PAPER

    def test_from_config_invalid_mode_falls_back_to_paper(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController.from_config({"go_live": {"mode": "INVALID"}})
        assert ctrl.mode is TradingMode.PAPER


class TestGoLiveControllerSetMetrics:
    """TC-11 — set_metrics ingests MetricsResult."""

    def test_set_metrics_from_metrics_result(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        from projects.polymarket.polyquantbot.phase9.metrics_validator import MetricsValidator

        ctrl = GoLiveController(mode=TradingMode.LIVE)
        validator = MetricsValidator(min_trades=0)

        for _ in range(5):
            validator.record_ev_signal(0.10, 0.09)
            validator.record_fill(True)
            validator.record_latency(200.0)
            validator.record_pnl_sample(float(_ * 10))

        metrics = validator.compute()
        ctrl.set_metrics(metrics)
        assert ctrl._metrics_ready is True
        assert ctrl._ev_capture_ratio == pytest.approx(metrics.ev_capture_ratio)


# ══════════════════════════════════════════════════════════════════════════════
# TC-12 – TC-17  ExecutionGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutionGuardValidation:
    """TC-12 – TC-16 — Individual validation failures and full pass."""

    def _guard(self, **kwargs) -> object:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        return ExecutionGuard(
            min_liquidity_usd=10_000.0,
            max_slippage_pct=0.03,
            max_position_usd=500.0,
            **kwargs,
        )

    def _valid_params(self) -> dict:
        return dict(
            market_id="0xabc",
            side="YES",
            price=0.62,
            size_usd=100.0,
            liquidity_usd=15_000.0,
            slippage_pct=0.01,
        )

    def test_low_liquidity_rejected(self) -> None:
        guard = self._guard()
        params = self._valid_params()
        params["liquidity_usd"] = 5_000.0  # below 10k
        result = guard.validate(**params)
        assert result.passed is False
        assert "insufficient_liquidity" in result.reason

    def test_high_slippage_rejected(self) -> None:
        guard = self._guard()
        params = self._valid_params()
        params["slippage_pct"] = 0.05  # above 3%
        result = guard.validate(**params)
        assert result.passed is False
        assert "slippage_exceeded" in result.reason

    def test_large_position_rejected(self) -> None:
        guard = self._guard()
        params = self._valid_params()
        params["size_usd"] = 1000.0  # above 500
        result = guard.validate(**params)
        assert result.passed is False
        assert "position_size_exceeded" in result.reason

    def test_duplicate_signature_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard

        class _FakeOrderGuard:
            _active = {"0xabc:YES:0.62:100.0": True}

        guard = ExecutionGuard(
            min_liquidity_usd=10_000.0,
            max_slippage_pct=0.03,
            max_position_usd=500.0,
            order_guard=_FakeOrderGuard(),
        )
        params = self._valid_params()
        params["order_guard_signature"] = "0xabc:YES:0.62:100.0"
        result = guard.validate(**params)
        assert result.passed is False
        assert "duplicate_order" in result.reason

    def test_all_checks_pass(self) -> None:
        guard = self._guard()
        result = guard.validate(**self._valid_params())
        assert result.passed is True
        assert result.reason == ""
        assert result.checks["liquidity"]["passed"] is True
        assert result.checks["slippage"]["passed"] is True
        assert result.checks["position_size"]["passed"] is True
        assert result.checks["no_duplicate"]["passed"] is True


class TestExecutionGuardFactory:
    """TC-17 — from_config factory."""

    def test_from_config_reads_markets_liquidity(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard

        config = {
            "markets": {"min_liquidity_usd": 20_000.0},
            "execution_guard": {
                "max_slippage_pct": 0.02,
                "max_position_usd": 250.0,
            },
        }
        guard = ExecutionGuard.from_config(config)
        assert guard._min_liquidity_usd == pytest.approx(20_000.0)
        assert guard._max_slippage_pct == pytest.approx(0.02)
        assert guard._max_position_usd == pytest.approx(250.0)

    def test_from_config_defaults(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard, _MIN_LIQUIDITY_USD

        guard = ExecutionGuard.from_config({})
        assert guard._min_liquidity_usd == pytest.approx(_MIN_LIQUIDITY_USD)


# ══════════════════════════════════════════════════════════════════════════════
# TC-18 – TC-24  KalshiClient (unit tests, no network)
# ══════════════════════════════════════════════════════════════════════════════

class TestKalshiClientHelpers:
    """TC-18 – TC-20 — Pure normalisation helper functions."""

    def test_cents_to_probability_normal(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _cents_to_probability
        assert _cents_to_probability(65) == pytest.approx(0.65)
        assert _cents_to_probability(0) == pytest.approx(0.0)
        assert _cents_to_probability(100) == pytest.approx(1.0)

    def test_cents_to_probability_clamps(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _cents_to_probability
        assert _cents_to_probability(150) == pytest.approx(1.0)
        assert _cents_to_probability(-10) == pytest.approx(0.0)

    def test_cents_to_probability_bad_input(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _cents_to_probability
        assert _cents_to_probability(None) == pytest.approx(0.0)
        assert _cents_to_probability("not_a_number") == pytest.approx(0.0)

    def test_normalise_timestamp_epoch_float(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _normalise_timestamp
        ts = 1700000000.0
        assert _normalise_timestamp(ts) == pytest.approx(ts)

    def test_normalise_timestamp_iso_string(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _normalise_timestamp
        # Should return a valid timestamp around the year 2024
        result = _normalise_timestamp("2024-11-05T18:00:00Z")
        assert result > 1700000000.0
        assert result < 1800000000.0

    def test_normalise_timestamp_none(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _normalise_timestamp
        result = _normalise_timestamp(None)
        assert abs(result - time.time()) < 5.0

    def test_map_outcome_yes(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _map_outcome
        assert _map_outcome("yes") == "YES"
        assert _map_outcome("YES") == "YES"
        assert _map_outcome("other") == "YES"

    def test_map_outcome_no(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import _map_outcome
        assert _map_outcome("no") == "NO"
        assert _map_outcome("NO") == "NO"


class TestKalshiClientNormalisation:
    """TC-21 – TC-22 — Market and trade normalisation."""

    def _client(self):
        from projects.polymarket.polyquantbot.connectors.kalshi_client import KalshiClient
        return KalshiClient()

    def test_normalise_market_basic(self) -> None:
        client = self._client()
        raw = {
            "ticker": "PRES-2024-REP",
            "title": "Will Republicans win the 2024 election?",
            "yes_ask": 55,
            "no_ask": 46,
            "volume": 500_000,
            "open_interest": 200_000,
            "close_time": "2024-11-05T20:00:00Z",
            "status": "open",
        }
        m = client._normalise_market(raw)
        assert m["ticker"] == "PRES-2024-REP"
        assert m["yes_price"] == pytest.approx(0.55)
        assert 0.0 <= m["no_price"] <= 1.0
        assert m["volume"] == pytest.approx(500_000.0)
        assert m["_source"] == "kalshi"

    def test_normalise_trade_basic(self) -> None:
        client = self._client()
        raw = {
            "trade_id": "t-001",
            "ticker": "PRES-2024-REP",
            "taker_side": "yes",
            "yes_price": 55,
            "count": 10,
            "created_time": "2024-11-01T12:00:00Z",
        }
        t = client._normalise_trade(raw, "PRES-2024-REP")
        assert t["trade_id"] == "t-001"
        assert t["side"] == "YES"
        assert t["price"] == pytest.approx(0.55)
        assert t["size"] == pytest.approx(10.0)
        assert t["_source"] == "kalshi"


class TestKalshiClientFailureFallback:
    """TC-23 – TC-24 — API failures return empty list, no crash."""

    async def test_get_markets_returns_empty_on_failure(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import KalshiClient

        client = KalshiClient(max_retries=1)
        # Patch _get to simulate total failure
        async def _fail(*args, **kwargs):
            return None

        client._get = _fail  # type: ignore[assignment]
        markets = await client.get_markets()
        assert markets == []

    async def test_get_trades_returns_empty_on_failure(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import KalshiClient

        client = KalshiClient(max_retries=1)

        async def _fail(*args, **kwargs):
            return None

        client._get = _fail  # type: ignore[assignment]
        trades = await client.get_trades("PRES-2024-REP")
        assert trades == []

    async def test_get_markets_handles_unexpected_response_shape(self) -> None:
        from projects.polymarket.polyquantbot.connectors.kalshi_client import KalshiClient

        client = KalshiClient()

        async def _wrong(*args, **kwargs):
            return "unexpected_string"

        client._get = _wrong  # type: ignore[assignment]
        markets = await client.get_markets()
        assert markets == []


# ══════════════════════════════════════════════════════════════════════════════
# TC-25 – TC-32  ArbDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestArbDetector:
    """TC-25 – TC-32 — Arbitrage detection logic."""

    def _detector(self, threshold: float = 0.04, market_map: Optional[dict] = None):
        from projects.polymarket.polyquantbot.phase10.arb_detector import ArbDetector
        return ArbDetector(
            spread_threshold=threshold,
            min_overlap_words=2,
            market_map=market_map or {},
        )

    def _poly(self, id: str, yes_price: float, title: str = "election president") -> dict:
        return {"id": id, "yes_price": yes_price, "title": title}

    def _kalshi(self, ticker: str, yes_price: float, title: str = "election president") -> dict:
        return {"ticker": ticker, "yes_price": yes_price, "title": title}

    def test_spread_below_threshold_no_signal(self) -> None:
        detector = self._detector(threshold=0.05)
        signals = detector.detect(
            polymarket_markets=[self._poly("0xabc", 0.65)],
            kalshi_markets=[self._kalshi("PRES-REP", 0.62)],
        )
        assert signals == []  # 0.03 < 0.05 → no signal

    def test_spread_above_threshold_signal_emitted(self) -> None:
        detector = self._detector(threshold=0.04)
        signals = detector.detect(
            polymarket_markets=[self._poly("0xabc", 0.65)],
            kalshi_markets=[self._kalshi("PRES-REP", 0.58)],
        )
        assert len(signals) == 1
        sig = signals[0]
        assert sig["_type"] == "arb_signal"
        assert sig["spread"] == pytest.approx(0.07)

    def test_buy_poly_direction_when_poly_price_lower(self) -> None:
        detector = self._detector(threshold=0.04)
        signals = detector.detect(
            polymarket_markets=[self._poly("0xabc", 0.55)],
            kalshi_markets=[self._kalshi("PRES-REP", 0.65)],
        )
        assert signals[0]["direction"] == "BUY_POLY"

    def test_buy_kalshi_direction_when_kalshi_price_lower(self) -> None:
        detector = self._detector(threshold=0.04)
        signals = detector.detect(
            polymarket_markets=[self._poly("0xabc", 0.70)],
            kalshi_markets=[self._kalshi("PRES-REP", 0.60)],
        )
        assert signals[0]["direction"] == "BUY_KALSHI"

    def test_empty_inputs_return_empty(self) -> None:
        detector = self._detector()
        assert detector.detect([], []) == []
        assert detector.detect([self._poly("0xabc", 0.6)], []) == []
        assert detector.detect([], [self._kalshi("PRES", 0.6)]) == []

    def test_exact_market_map_match_takes_precedence(self) -> None:
        detector = self._detector(
            threshold=0.04,
            market_map={"0xabc": "EXACT-TICKER"},
        )
        signals = detector.detect(
            polymarket_markets=[self._poly("0xabc", 0.70, "unrelated title xyz")],
            kalshi_markets=[
                self._kalshi("EXACT-TICKER", 0.60, "completely different words"),
                self._kalshi("OTHER", 0.60, "unrelated title xyz"),
            ],
        )
        # Should match via market_map to EXACT-TICKER, spread = 0.10
        assert len(signals) == 1
        assert signals[0]["kalshi_ticker"] == "EXACT-TICKER"

    def test_fuzzy_title_matching(self) -> None:
        detector = self._detector(threshold=0.04)
        poly = [{"id": "0xdef", "yes_price": 0.72, "title": "Will Trump win the 2024 election?"}]
        kalshi = [
            {"ticker": "TRUMP-WIN", "yes_price": 0.62, "title": "Trump wins the 2024 election"},
        ]
        signals = detector.detect(poly, kalshi)
        assert len(signals) == 1
        assert signals[0]["spread"] == pytest.approx(0.10)

    def test_bad_market_data_skipped_without_crash(self) -> None:
        detector = self._detector(threshold=0.04)
        bad_poly = [{"id": None, "yes_price": None, "title": None}]
        kalshi = [self._kalshi("PRES-REP", 0.55)]
        # Should not raise
        signals = detector.detect(bad_poly, kalshi)
        # May or may not emit a signal, but must not raise
        assert isinstance(signals, list)


# ══════════════════════════════════════════════════════════════════════════════
# TC-33 – TC-34  MetricsResult go_live_ready field
# ══════════════════════════════════════════════════════════════════════════════

class TestMetricsResultGoLiveReady:
    """TC-33 – TC-34 — go_live_ready field on MetricsResult."""

    def _validator_with_trades(
        self,
        n: int = 30,
        latency_ms: float = 300.0,
        ev_ratio: float = 0.9,
        fill_frac: float = 1.0,
    ):
        from projects.polymarket.polyquantbot.phase9.metrics_validator import MetricsValidator

        v = MetricsValidator(
            ev_capture_target=0.75,
            fill_rate_target=0.60,
            p95_latency_target_ms=500.0,
            max_drawdown_target=0.08,
            min_trades=n,
        )
        fill_count = int(n * fill_frac)
        for i in range(n):
            v.record_ev_signal(0.10, 0.10 * ev_ratio)
            v.record_fill(i < fill_count)
            v.record_latency(latency_ms)
            v.record_pnl_sample(float(i * 5))
        return v

    def test_go_live_ready_true_when_all_gates_pass(self) -> None:
        v = self._validator_with_trades()
        result = v.compute()
        assert result.go_live_ready is True
        assert result.pass_result is True
        assert result.go_live_ready == result.pass_result

    def test_go_live_ready_false_when_latency_fails(self) -> None:
        v = self._validator_with_trades(latency_ms=800.0)  # above 500ms threshold
        result = v.compute()
        assert result.go_live_ready is False
        assert result.pass_result is False

    def test_go_live_ready_matches_pass_result(self) -> None:
        """go_live_ready must always equal pass_result."""
        for latency in (200.0, 600.0):
            v = self._validator_with_trades(latency_ms=latency)
            result = v.compute()
            assert result.go_live_ready == result.pass_result
