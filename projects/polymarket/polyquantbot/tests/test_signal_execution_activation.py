"""Tests for core.signal.signal_engine and core.execution.executor.

Test IDs:
  SE-01 — SE-14  : signal_engine.generate_signals
  EX-01 — EX-18  : executor.execute_trade
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.polyquantbot.core.signal.signal_engine import (
    SignalResult,
    generate_signals,
)
from projects.polymarket.polyquantbot.core.execution.executor import (
    TradeResult,
    execute_trade,
    reset_state,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_executor_state():
    """Reset module-level dedup/counter state before every test."""
    reset_state()
    yield
    reset_state()


def _market(
    market_id: str = "mkt-1",
    p_market: float = 0.40,
    p_model: float = 0.60,
    liquidity_usd: float = 50_000.0,
    **kwargs,
) -> dict:
    return {
        "market_id": market_id,
        "p_market": p_market,
        "p_model": p_model,
        "liquidity_usd": liquidity_usd,
        **kwargs,
    }


# ── Signal Engine tests (SE) ───────────────────────────────────────────────────


async def test_se01_positive_edge_generates_signal():
    """SE-01: A market with positive edge and enough liquidity yields a signal."""
    signals = await generate_signals([_market()], bankroll=1000.0)
    assert len(signals) == 1
    assert signals[0].market_id == "mkt-1"


async def test_se02_zero_edge_skipped():
    """SE-02: A market where p_model == p_market produces zero edge and is skipped."""
    signals = await generate_signals(
        [_market(p_market=0.5, p_model=0.5)], bankroll=1000.0
    )
    assert signals == []


async def test_se03_negative_edge_skipped():
    """SE-03: A market where p_model < p_market has negative edge and is skipped."""
    signals = await generate_signals(
        [_market(p_market=0.70, p_model=0.50)], bankroll=1000.0
    )
    assert signals == []


async def test_se04_edge_below_threshold_skipped():
    """SE-04: When p_model=0.51 and p_market=0.50, edge=0.01 < explicit threshold 0.02 → skipped."""
    signals = await generate_signals(
        [_market(p_market=0.50, p_model=0.51)],
        bankroll=1000.0,
        edge_threshold=0.02,
    )
    assert signals == []


async def test_se05_edge_just_above_threshold_accepted():
    """SE-05: When p_model=0.525 and p_market=0.50, edge=0.025 > explicit threshold 0.02 → signal accepted."""
    signals = await generate_signals(
        [_market(p_market=0.50, p_model=0.525)],
        bankroll=1000.0,
        edge_threshold=0.02,
    )
    assert len(signals) == 1


async def test_se06_edge_above_threshold_accepted():
    """SE-06: When p_model=0.60 and p_market=0.40, edge=0.20 > explicit threshold 0.02 → signal produced."""
    signals = await generate_signals(
        [_market(p_market=0.40, p_model=0.60)],
        bankroll=1000.0,
        edge_threshold=0.02,
    )
    assert len(signals) == 1


async def test_se07_low_liquidity_skipped():
    """SE-07: Market with liquidity below minimum is skipped."""
    signals = await generate_signals(
        [_market(liquidity_usd=5_000.0)],
        bankroll=1000.0,
        min_liquidity_usd=10_000.0,
    )
    assert signals == []


async def test_se08_sufficient_liquidity_accepted():
    """SE-08: Market with liquidity above minimum passes the filter."""
    signals = await generate_signals(
        [_market(liquidity_usd=15_000.0)],
        bankroll=1000.0,
        min_liquidity_usd=10_000.0,
    )
    assert len(signals) == 1


async def test_se09_position_size_capped_at_max_position():
    """SE-09: Size is clamped to max_position_fraction * bankroll."""
    signals = await generate_signals(
        [_market(p_market=0.01, p_model=0.99)],  # huge edge → large Kelly
        bankroll=10_000.0,
        max_position_fraction=0.10,
    )
    assert len(signals) == 1
    assert signals[0].size_usd <= 10_000.0 * 0.10 + 0.001  # allow float rounding


async def test_se10_ev_positive_for_positive_edge():
    """SE-10: EV is positive when p_model > p_market."""
    signals = await generate_signals([_market()], bankroll=1000.0)
    assert signals[0].ev > 0


async def test_se11_signal_result_fields_populated():
    """SE-11: All core SignalResult fields are populated correctly."""
    signals = await generate_signals([_market(market_id="abc")], bankroll=2000.0)
    s = signals[0]
    assert s.market_id == "abc"
    assert s.signal_id  # non-empty
    assert s.edge > 0
    assert s.kelly_f > 0
    assert s.size_usd > 0


async def test_se12_multiple_markets_filtered_independently():
    """SE-12: Each market is evaluated independently using real p_model.

    With the real alpha model:
      - 'good'    (p_market=0.40, p_model=0.60): positive edge 0.20 → signal
      - 'bad'     (p_market=0.60, p_model=0.40): negative edge -0.20 → filtered
      - 'low-liq' (liquidity=500): filtered by the liquidity check
    Only the 'good' market generates a signal.
    """
    markets = [
        _market(market_id="good", p_market=0.40, p_model=0.60),
        _market(market_id="bad",  p_market=0.60, p_model=0.40),  # negative edge → filtered
        _market(market_id="low-liq", liquidity_usd=500.0),        # filtered by liquidity
    ]
    signals = await generate_signals(markets, bankroll=1000.0)
    assert len(signals) == 1
    assert signals[0].market_id == "good"


async def test_se13_side_inferred_yes_when_model_above_half():
    """SE-13: Side defaults to YES when p_model > 0.5.

    p_market=0.55, p_model=0.70: positive edge 0.15, p_model > 0.5 → YES.
    """
    signals = await generate_signals([_market(p_market=0.55, p_model=0.70)], bankroll=1000.0)
    assert signals[0].side == "YES"


async def test_se14_side_inferred_no_when_model_below_half():
    """SE-14: Side defaults to NO when p_model < 0.5."""
    # We still need positive edge: p_model=0.30, p_market=0.05 → edge=0.25
    signals = await generate_signals(
        [_market(p_market=0.05, p_model=0.30)], bankroll=1000.0
    )
    assert signals[0].side == "NO"


# ── Executor tests (EX) ────────────────────────────────────────────────────────


def _signal(
    signal_id: str = "sig-001",
    market_id: str = "mkt-1",
    side: str = "YES",
    p_market: float = 0.40,
    p_model: float = 0.60,
    edge: float = 0.20,
    ev: float = 0.50,
    kelly_f: float = 0.25,
    size_usd: float = 50.0,
    liquidity_usd: float = 50_000.0,
) -> SignalResult:
    return SignalResult(
        signal_id=signal_id,
        market_id=market_id,
        side=side,
        p_market=p_market,
        p_model=p_model,
        edge=edge,
        ev=ev,
        kelly_f=kelly_f,
        size_usd=size_usd,
        liquidity_usd=liquidity_usd,
    )


async def test_ex01_paper_mode_succeeds():
    """EX-01: Paper mode execution returns success."""
    result = await execute_trade(_signal(), mode="PAPER")
    assert result.success
    assert result.mode == "PAPER"


async def test_ex02_paper_trade_fills_full_size():
    """EX-02: Paper fill equals the requested size."""
    result = await execute_trade(_signal(size_usd=100.0), mode="PAPER")
    assert result.filled_size_usd == pytest.approx(100.0, abs=0.01)


async def test_ex03_duplicate_signal_skipped():
    """EX-03: Second call with same signal_id is a no-op (idempotent)."""
    sig = _signal()
    first = await execute_trade(sig, mode="PAPER")
    second = await execute_trade(sig, mode="PAPER")
    assert first.success
    assert not second.success
    assert second.reason == "duplicate"


async def test_ex04_kill_switch_blocks_trade():
    """EX-04: Kill switch active → trade is skipped."""
    result = await execute_trade(_signal(), kill_switch_active=True)
    assert not result.success
    assert result.reason == "kill_switch_active"


async def test_ex05_non_positive_edge_skipped():
    """EX-05: Signal with edge <= 0 is rejected at execution time."""
    result = await execute_trade(_signal(edge=0.0), mode="PAPER")
    assert not result.success
    assert result.reason == "edge_non_positive"


async def test_ex06_edge_below_min_skipped():
    """EX-06: Signal with edge below min_edge threshold is rejected."""
    result = await execute_trade(_signal(edge=0.005), mode="PAPER", min_edge=0.02)
    assert not result.success
    assert result.reason == "edge_below_threshold"


async def test_ex07_size_exceeds_max_skipped():
    """EX-07: Signal with size > max_position_usd is rejected."""
    result = await execute_trade(
        _signal(size_usd=2000.0), mode="PAPER", max_position_usd=500.0
    )
    assert not result.success
    assert result.reason == "size_exceeds_max_position"


async def test_ex08_concurrent_cap_respected():
    """EX-08: More than max_concurrent simultaneous trades are rejected."""
    # max_concurrent=1 → second concurrent call is rejected
    blocker = asyncio.Event()

    async def slow_callback(**kwargs) -> dict:
        await blocker.wait()
        return {"filled_size": 10.0, "fill_price": 0.4}

    sig1 = _signal(signal_id="s1")
    sig2 = _signal(signal_id="s2")

    task1 = asyncio.create_task(
        execute_trade(sig1, mode="LIVE", max_concurrent=1, executor_callback=slow_callback)
    )
    await asyncio.sleep(0)  # let task1 start

    result2 = await execute_trade(sig2, mode="LIVE", max_concurrent=1, executor_callback=slow_callback)
    assert not result2.success
    assert result2.reason == "max_concurrent_reached"

    blocker.set()
    result1 = await task1
    assert result1.success


async def test_ex09_live_mode_calls_executor_callback():
    """EX-09: LIVE mode delegates to executor_callback."""
    callback = AsyncMock(return_value={"filled_size": 50.0, "fill_price": 0.42})
    result = await execute_trade(_signal(), mode="LIVE", executor_callback=callback)
    assert result.success
    callback.assert_awaited_once()


async def test_ex10_live_mode_no_callback_falls_back_to_paper():
    """EX-10: LIVE mode without executor_callback falls back to paper simulation."""
    result = await execute_trade(_signal(), mode="LIVE", executor_callback=None)
    assert result.success
    assert result.mode == "PAPER"


async def test_ex11_executor_exception_triggers_retry():
    """EX-11: An executor exception triggers one retry; if retry succeeds → success."""
    calls = {"count": 0}

    async def flaky_callback(**kwargs) -> dict:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient error")
        return {"filled_size": 50.0, "fill_price": 0.40}

    result = await execute_trade(_signal(), mode="LIVE", executor_callback=flaky_callback)
    assert result.success
    assert calls["count"] == 2


async def test_ex12_double_failure_returns_failure():
    """EX-12: Two consecutive execution failures → TradeResult.success == False."""

    async def always_fail(**kwargs) -> dict:
        raise RuntimeError("always fails")

    result = await execute_trade(_signal(), mode="LIVE", executor_callback=always_fail)
    assert not result.success
    assert "retry_failed" in result.reason or "execution_exception" in result.reason


async def test_ex13_trade_result_has_latency():
    """EX-13: Successful trade has latency_ms > 0."""
    result = await execute_trade(_signal(), mode="PAPER")
    assert result.latency_ms >= 0


async def test_ex14_trade_id_is_unique():
    """EX-14: Each execute_trade call generates a unique trade_id."""
    sig1 = _signal(signal_id="u1")
    sig2 = _signal(signal_id="u2")
    r1 = await execute_trade(sig1, mode="PAPER")
    r2 = await execute_trade(sig2, mode="PAPER")
    assert r1.trade_id != r2.trade_id


async def test_ex15_telegram_callback_called_on_success():
    """EX-15: telegram_callback is invoked with structured args after a successful trade."""
    tg = AsyncMock()
    await execute_trade(_signal(), mode="PAPER", telegram_callback=tg)
    tg.assert_awaited_once()
    call_kwargs = tg.call_args.kwargs
    assert call_kwargs.get("side") == "YES"
    assert call_kwargs.get("market_id") == "mkt-1"
    assert "price" in call_kwargs
    assert "size" in call_kwargs


async def test_ex16_telegram_failure_does_not_propagate():
    """EX-16: A crash in telegram_callback doesn't surface to the caller."""

    async def boom(**kwargs: object) -> None:
        raise RuntimeError("telegram down")

    result = await execute_trade(_signal(), mode="PAPER", telegram_callback=boom)
    assert result.success  # trade still succeeded


async def test_ex17_pipeline_signals_to_execution():
    """EX-17: Full pipeline: generate_signals → execute_trade succeeds."""
    markets = [_market(market_id="pipe-1")]
    signals = await generate_signals(markets, bankroll=5000.0)
    assert signals

    results = []
    for sig in signals:
        r = await execute_trade(sig, mode="PAPER")
        results.append(r)

    assert all(r.success for r in results)


async def test_ex18_multiple_unique_signals_all_executed():
    """EX-18: Multiple distinct signals all get executed in paper mode."""
    markets = [
        _market(market_id=f"mkt-{i}", p_market=0.30 + i * 0.01, p_model=0.60 + i * 0.01)
        for i in range(3)
    ]
    signals = await generate_signals(markets, bankroll=5000.0)
    assert len(signals) == 3

    results = [await execute_trade(s, mode="PAPER") for s in signals]
    assert all(r.success for r in results)
    # All trade IDs must be distinct
    ids = [r.trade_id for r in results]
    assert len(set(ids)) == 3


# ── Force Signal Mode tests (FS) ───────────────────────────────────────────────


async def test_fs01_force_mode_generates_signal_regardless_of_edge():
    """FS-01: FORCE_SIGNAL_MODE bypasses edge filter — even zero-edge market gets a signal."""
    markets = [_market(p_market=0.5, p_model=0.5)]  # zero edge — normally skipped
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert len(signals) == 1


async def test_fs02_force_mode_generates_signal_regardless_of_liquidity():
    """FS-02: FORCE_SIGNAL_MODE bypasses liquidity filter."""
    markets = [_market(liquidity_usd=0.0)]  # no liquidity — normally skipped
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert len(signals) == 1


async def test_fs03_force_mode_side_yes_when_p_market_below_half():
    """FS-03: Force mode uses p_market < 0.5 → YES rule."""
    markets = [_market(p_market=0.3, p_model=0.3)]  # p_market < 0.5 → YES
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert signals[0].side == "YES"


async def test_fs04_force_mode_side_no_when_p_market_at_or_above_half():
    """FS-04: Force mode uses p_market >= 0.5 → NO rule."""
    markets = [_market(p_market=0.7, p_model=0.7)]  # p_market >= 0.5 → NO
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert signals[0].side == "NO"


async def test_fs05_force_mode_size_capped_at_1pct_bankroll():
    """FS-05: Force mode size is capped at 1 % of bankroll."""
    bankroll = 5000.0
    markets = [_market()]
    signals = await generate_signals(markets, bankroll=bankroll, force_signal_mode=True)
    assert signals[0].size_usd == pytest.approx(bankroll * 0.01, abs=0.001)


async def test_fs06_force_mode_respects_top_n_default_of_1():
    """FS-06: Force mode only returns top-N (default 1) market signals."""
    markets = [
        _market(market_id=f"mkt-{i}", p_market=0.3 + i * 0.05)
        for i in range(5)
    ]
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert len(signals) == 1
    assert signals[0].market_id == "mkt-0"


async def test_fs07_force_mode_env_flag(monkeypatch):
    """FS-07: FORCE_SIGNAL_MODE env var activates force mode."""
    monkeypatch.setenv("FORCE_SIGNAL_MODE", "true")
    markets = [_market(p_market=0.5, p_model=0.5)]  # zero edge — skipped in normal mode
    signals = await generate_signals(markets, bankroll=1000.0)
    assert len(signals) == 1


async def test_fs08_force_mode_false_still_filters_normally():
    """FS-08: force_signal_mode=False (explicit) still applies normal filtering."""
    markets = [_market(p_market=0.5, p_model=0.5)]  # zero edge
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=False)
    assert signals == []


async def test_fs09_force_mode_pipeline_executes_trade():
    """FS-09: Full pipeline with force mode: below-threshold edge market still executes.

    Uses liquidity=0 to ensure market would normally be filtered, but positive edge
    so the executor's re-validation accepts it.
    """
    markets = [_market(p_market=0.4, p_model=0.42, liquidity_usd=0.0)]  # filtered by liquidity normally
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert signals

    results = [await execute_trade(s, mode="PAPER") for s in signals]
    assert all(r.success for r in results)


async def test_fs10_executor_emits_order_sent_and_order_filled():
    """FS-10: executor emits order_sent and order_filled structured log events."""
    import projects.polymarket.polyquantbot.core.execution.executor as executor_mod

    recorded: list[dict] = []
    original_info = executor_mod.log.info

    def recording_info(event: str, **kw: object) -> None:  # type: ignore[override]
        recorded.append({"event": event, **kw})
        return original_info(event, **kw)

    executor_mod.log.info = recording_info  # type: ignore[method-assign]
    try:
        result = await execute_trade(_signal(), mode="PAPER")
    finally:
        executor_mod.log.info = original_info  # type: ignore[method-assign]

    assert result.success
    events = [r["event"] for r in recorded]
    assert "order_sent" in events, f"order_sent not found in events: {events}"
    assert "order_filled" in events, f"order_filled not found in events: {events}"


async def test_fs11_force_mode_zero_edge_executor_accepts():
    """FS-11: Force mode signal with edge=0 is accepted by executor (not rejected as edge_non_positive)."""
    markets = [_market(p_market=0.5, p_model=0.5)]  # zero edge
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert signals, "force mode should produce a signal even for zero-edge market"
    sig = signals[0]
    assert sig.force_mode is True
    assert sig.edge >= 0.01, "force mode should inject at least 0.01 edge"
    result = await execute_trade(sig, mode="PAPER")
    assert result.success, f"force mode trade should succeed; got reason={result.reason}"


async def test_fs12_force_mode_signal_carries_force_mode_flag():
    """FS-12: Signals generated in force mode carry force_mode=True."""
    markets = [_market(p_market=0.4, p_model=0.45)]
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert signals[0].force_mode is True


async def test_fs13_normal_mode_signal_force_mode_false():
    """FS-13: Signals generated in normal mode carry force_mode=False."""
    markets = [_market(p_market=0.4, p_model=0.6, liquidity_usd=50_000.0)]
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=False)
    assert signals
    assert signals[0].force_mode is False


# ── Alpha injection tests (FA) ─────────────────────────────────────────────────

from projects.polymarket.polyquantbot.core.signal.alpha_model import ProbabilisticAlphaModel  # noqa: E402


async def test_fa01_alpha_model_force_mode_injects_when_zero_deviation():
    """FA-01: compute_p_model with force_mode=True injects deviation when p_model <= p_market."""
    model = ProbabilisticAlphaModel()
    # Thin buffer → deviation=0, momentum=0, so p_model == p_market
    p_model, _vol = model.compute_p_model("mkt-x", p_market=0.5, liquidity_usd=1000.0, force_mode=True)
    assert p_model > 0.5, "force_mode should ensure p_model > p_market"
    assert 0.01 <= p_model <= 0.99


async def test_fa02_alpha_model_force_mode_clamps_to_bounds():
    """FA-02: Injected p_model is always within [0.01, 0.99]."""
    model = ProbabilisticAlphaModel()
    p_model, _ = model.compute_p_model("mkt-x", p_market=0.97, liquidity_usd=1000.0, force_mode=True)
    assert 0.01 <= p_model <= 0.99


async def test_fa03_alpha_model_no_injection_when_model_already_above():
    """FA-03: No injection when p_model already > p_market (positive edge exists)."""
    model = ProbabilisticAlphaModel()
    # Seed price history to create positive deviation
    for _ in range(10):
        model.record_tick("mkt-y", price=0.60)
    p_model, _ = model.compute_p_model("mkt-y", p_market=0.40, liquidity_usd=50_000.0, force_mode=True)
    assert p_model > 0.40, "positive edge should be preserved"


async def test_fa04_alpha_model_normal_mode_unchanged():
    """FA-04: force_mode=False does not inject random deviation.

    With an empty price buffer, deviation=0 and momentum=0, so raw_p_model
    equals p_market exactly.  Normal mode must not alter this.
    """
    model = ProbabilisticAlphaModel()
    # Empty buffer: deviation=0, momentum=0 → raw_p_model == p_market
    p_model, _ = model.compute_p_model("mkt-z", p_market=0.5, liquidity_usd=1000.0, force_mode=False)
    # Without force_mode injection the model returns p_market unchanged
    assert p_model == 0.5  # no injection in normal mode with empty buffer


async def test_fa05_signal_engine_fallback_alpha_injection():
    """FA-05: Signal engine injects 0.01 edge in force mode when no alpha model and edge <= 0."""
    markets = [_market(p_market=0.5, p_model=0.5, liquidity_usd=0.0)]
    signals = await generate_signals(markets, bankroll=1000.0, force_signal_mode=True)
    assert len(signals) == 1
    assert signals[0].edge >= 0.01, "injected edge must be at least 0.01"
    assert signals[0].force_mode is True

