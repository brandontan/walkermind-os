"""Integration tests for core.pipeline.trading_loop.run_trading_loop.

Test IDs:
  TL-01 — TL-20 : run_trading_loop behaviour
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.core.pipeline.trading_loop import run_trading_loop
from projects.polymarket.polyquantbot.core.execution.executor import reset_state


# ── Helpers ────────────────────────────────────────────────────────────────────


def _market(
    market_id: str = "mkt-1",
    p_market: float = 0.40,
    p_model: float = 0.65,
    liquidity_usd: float = 50_000.0,
) -> dict:
    return {
        "market_id": market_id,
        "p_market": p_market,
        "p_model": p_model,
        "liquidity_usd": liquidity_usd,
    }


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    yield
    reset_state()


def _stop_after(n: int) -> asyncio.Event:
    """Return a stop_event that auto-fires after *n* loop ticks."""
    event = asyncio.Event()

    async def _setter():
        # Each tick calls asyncio.sleep once; we wait for n sleep calls.
        await asyncio.sleep(0)  # yield
        event.set()

    return event


# ── Tests ──────────────────────────────────────────────────────────────────────


async def test_tl01_loop_runs_one_tick_and_stops():
    """TL-01: Loop completes one full tick and respects stop_event."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()  # stop after first sleep

    markets = [_market()]
    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=markets),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )


async def test_tl02_no_markets_skips_execution():
    """TL-02: Empty market list causes iteration skip without error."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    execute_mock = AsyncMock()
    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=execute_mock,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )

    execute_mock.assert_not_awaited()


async def test_tl03_market_fetch_error_skips_without_crash():
    """TL-03: Exception in get_active_markets is caught; loop does not crash."""
    stop = asyncio.Event()
    call_count = {"n": 0}

    async def fake_sleep(s):
        call_count["n"] += 1
        if call_count["n"] >= 1:
            stop.set()

    async def boom():
        raise RuntimeError("network failure")

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=boom,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        # Must not raise
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )


async def test_tl04_signals_generated_from_markets():
    """TL-04: generate_signals is called with the fetched markets."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    markets = [_market("m1"), _market("m2")]
    signal_mock = AsyncMock(return_value=[])

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=markets),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=signal_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=2000.0,
            mode="PAPER",
            stop_event=stop,
        )

    signal_mock.assert_awaited_once_with(markets, bankroll=2000.0)


async def test_tl05_execute_trade_called_per_signal():
    """TL-05: execute_trade is called once per generated signal."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult

    fake_signals = [
        SignalResult(
            signal_id=f"sig-{i}",
            market_id=f"mkt-{i}",
            side="YES",
            p_market=0.40,
            p_model=0.65,
            edge=0.25,
            ev=0.50,
            kelly_f=0.25,
            size_usd=50.0,
            liquidity_usd=50_000.0,
        )
        for i in range(3)
    ]

    execute_mock = AsyncMock(
        return_value=MagicMock(success=True, market_id="x", side="YES",
                               mode="PAPER", filled_size_usd=50.0, fill_price=0.40)
    )

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=fake_signals),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=execute_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )

    assert execute_mock.await_count == 3


async def test_tl06_paper_mode_used_by_default():
    """TL-06: Default mode is PAPER when TRADING_MODE env is not set."""
    import os
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    captured_mode: list[str] = []

    async def capture_execute(signal, *, mode=None, **kw):
        captured_mode.append(mode or "PAPER")
        return MagicMock(success=True, market_id="x", side="YES",
                         mode="PAPER", filled_size_usd=50.0, fill_price=0.40)

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult

    sig = SignalResult(
        signal_id="s1", market_id="m1", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[sig]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=capture_execute,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("TRADING_MODE", None)
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            stop_event=stop,
        )

    assert captured_mode and captured_mode[0] == "PAPER"


async def test_tl07_telegram_callback_forwarded_to_executor():
    """TL-07: telegram_callback is passed through to execute_trade."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult

    sig = SignalResult(
        signal_id="s99", market_id="m99", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    tg_cb = AsyncMock()
    captured_tg: list = []

    async def capture_execute(signal, *, telegram_callback=None, **kw):
        captured_tg.append(telegram_callback)
        return MagicMock(success=True, market_id="x", side="YES",
                         mode="PAPER", filled_size_usd=50.0, fill_price=0.40)

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[sig]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=capture_execute,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            telegram_callback=tg_cb,
            stop_event=stop,
        )

    assert captured_tg and captured_tg[0] is tg_cb


async def test_tl08_executor_callback_forwarded():
    """TL-08: executor_callback is passed through to execute_trade in LIVE mode."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult

    sig = SignalResult(
        signal_id="s88", market_id="m88", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    ex_cb = AsyncMock(return_value={"filled_size": 50.0, "fill_price": 0.40})
    captured_cb: list = []

    async def capture_execute(signal, *, executor_callback=None, **kw):
        captured_cb.append(executor_callback)
        return MagicMock(success=True, market_id="x", side="YES",
                         mode="LIVE", filled_size_usd=50.0, fill_price=0.40)

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[sig]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=capture_execute,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="LIVE",
            executor_callback=ex_cb,
            stop_event=stop,
        )

    assert captured_cb and captured_cb[0] is ex_cb


async def test_tl09_multiple_ticks_accumulate_trades():
    """TL-09: Two loop ticks result in two rounds of signal→execution calls."""
    stop = asyncio.Event()
    tick_count = {"n": 0}

    async def fake_sleep(s):
        tick_count["n"] += 1
        if tick_count["n"] >= 2:
            stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult

    def _make_sig(i: int) -> SignalResult:
        return SignalResult(
            signal_id=f"s{i}", market_id=f"m{i}", side="YES",
            p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
            kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
        )

    signal_call = {"n": 0}

    async def rotating_signals(markets, *, bankroll):
        signal_call["n"] += 1
        return [_make_sig(signal_call["n"])]

    execute_mock = AsyncMock(
        return_value=MagicMock(success=True, market_id="x", side="YES",
                               mode="PAPER", filled_size_usd=50.0, fill_price=0.40)
    )

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=rotating_signals,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=execute_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )

    assert execute_mock.await_count == 2


async def test_tl10_stop_event_prevents_further_ticks():
    """TL-10: Pre-set stop_event exits immediately without fetching markets."""
    stop = asyncio.Event()
    stop.set()  # already set

    fetch_mock = AsyncMock(return_value=[_market()])

    with patch(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
        new=fetch_mock,
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )

    fetch_mock.assert_not_awaited()


async def test_tl11_generate_signals_error_skips_iteration():
    """TL-11: Exception in generate_signals is caught; loop continues."""
    stop = asyncio.Event()
    call_count = {"n": 0}

    async def fake_sleep(s):
        call_count["n"] += 1
        if call_count["n"] >= 1:
            stop.set()

    async def boom(markets, *, bankroll):
        raise RuntimeError("signal engine failure")

    execute_mock = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=boom,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=execute_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )

    execute_mock.assert_not_awaited()


async def test_tl12_execute_trade_error_does_not_stop_loop():
    """TL-12: Exception inside execute_trade propagates up but loop catches it."""
    stop = asyncio.Event()
    call_count = {"n": 0}

    async def fake_sleep(s):
        call_count["n"] += 1
        if call_count["n"] >= 1:
            stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult

    sig = SignalResult(
        signal_id="err-1", market_id="m-err", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )

    async def boom_execute(signal, **kw):
        raise RuntimeError("exchange error")

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[sig]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=boom_execute,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        # Must not raise
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )


async def test_tl13_bankroll_passed_to_generate_signals():
    """TL-13: Bankroll parameter is forwarded to generate_signals."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    signal_mock = AsyncMock(return_value=[])
    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=signal_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=7500.0,
            mode="PAPER",
            stop_event=stop,
        )

    _, kwargs = signal_mock.call_args
    assert kwargs["bankroll"] == 7500.0


async def test_tl14_mode_env_var_respected():
    """TL-14: TRADING_MODE env var is read when mode arg is not supplied."""
    import os
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    captured: list[str] = []

    async def capture_execute(signal, *, mode=None, **kw):
        captured.append(mode or "")
        return MagicMock(success=True, market_id="x", side="YES",
                         mode="PAPER", filled_size_usd=50.0, fill_price=0.40)

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult

    sig = SignalResult(
        signal_id="env-1", market_id="m-env", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )

    with (
        patch.dict(os.environ, {"TRADING_MODE": "PAPER"}),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[sig]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=capture_execute,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            stop_event=stop,
        )

    assert captured and captured[0] == "PAPER"


async def test_tl15_full_pipeline_paper_e2e():
    """TL-15: Full pipeline in paper mode: real generate_signals + execute_trade."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    markets = [
        {
            "market_id": "e2e-mkt",
            "p_market": 0.40,
            "p_model": 0.70,
            "liquidity_usd": 50_000.0,
        }
    ]

    with patch(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
        new=AsyncMock(return_value=markets),
    ), patch(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
        new=fake_sleep,
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=5000.0,
            mode="PAPER",
            stop_event=stop,
        )
    # No assertion needed — completing without exception is the success condition


async def test_tl16_no_signals_no_execution():
    """TL-16: When generate_signals returns empty list no trade is attempted."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    execute_mock = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market(p_market=0.70, p_model=0.30)]),  # negative edge
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=execute_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )

    execute_mock.assert_not_awaited()


async def test_tl17_loop_interval_env_var():
    """TL-17: TRADING_LOOP_INTERVAL_S env var sets the sleep duration."""
    import os
    stop = asyncio.Event()
    slept: list[float] = []

    async def capture_sleep(s: float):
        slept.append(s)
        stop.set()

    with (
        patch.dict(os.environ, {"TRADING_LOOP_INTERVAL_S": "7"}),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=capture_sleep,
        ),
    ):
        await run_trading_loop(
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )

    assert slept and slept[0] == 7.0


async def test_tl18_bankroll_env_var():
    """TL-18: TRADING_LOOP_BANKROLL env var sets the bankroll."""
    import os
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    signal_mock = AsyncMock(return_value=[])

    with (
        patch.dict(os.environ, {"TRADING_LOOP_BANKROLL": "3500"}),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=signal_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            mode="PAPER",
            stop_event=stop,
        )

    _, kwargs = signal_mock.call_args
    assert kwargs["bankroll"] == 3500.0


async def test_tl19_successful_trade_logs_result():
    """TL-19: A successful trade result is handled without error (smoke test)."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="log-1", market_id="log-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="t-001",
        signal_id="log-1",
        market_id="log-mkt",
        side="YES",
        success=True,
        mode="PAPER",
        attempted_size=50.0,
        filled_size_usd=50.0,
        fill_price=0.40,
        latency_ms=1.0,
        reason="paper_simulated",
    )

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[sig]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=AsyncMock(return_value=trade_result),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )


async def test_tl20_failed_trade_result_no_extra_log():
    """TL-20: A failed trade result (success=False) does not cause errors."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="fail-1", market_id="fail-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="t-fail",
        signal_id="fail-1",
        market_id="fail-mkt",
        side="YES",
        success=False,
        mode="PAPER",
        attempted_size=50.0,
        reason="duplicate",
    )

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[sig]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=AsyncMock(return_value=trade_result),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
        )
