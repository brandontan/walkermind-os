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


def _make_mock_db() -> AsyncMock:
    """Create a mock DatabaseClient that satisfies the trading loop db requirement."""
    db = AsyncMock()
    db.upsert_position = AsyncMock(return_value=True)
    db.insert_trade = AsyncMock(return_value=True)
    db.update_trade_status = AsyncMock(return_value=True)
    db.get_positions = AsyncMock(return_value=[])
    db.get_recent_trades = AsyncMock(return_value=[])
    return db


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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
        )

    signal_mock.assert_awaited_once()
    call_args = signal_mock.await_args
    assert call_args.args == (markets,)
    assert call_args.kwargs["bankroll"] == 2000.0
    assert "alpha_model" in call_args.kwargs


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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
        )

    assert captured_mode and captured_mode[0] == "PAPER"


async def test_tl07_telegram_callback_called_by_trading_loop():
    """TL-07: telegram_callback is called directly by the trading loop (not forwarded to
    execute_trade) with a pre-formatted string message after a successful trade.
    """
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
    captured_executor_tg: list = []

    async def capture_execute(signal, *, telegram_callback=None, **kw):
        # Capture what was (or was not) passed to execute_trade
        captured_executor_tg.append(telegram_callback)
        return MagicMock(
            success=True, market_id="x", side="YES", mode="PAPER",
            filled_size_usd=50.0, fill_price=0.40,
            attempted_size=50.0, slippage_pct=0.005, partial_fill=False,
            trade_id="t-test",
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
    ):
        await run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            telegram_callback=tg_cb,
            stop_event=stop,
            db=_make_mock_db(),
        )

    # telegram_callback is no longer forwarded to execute_trade; it is called
    # directly by the trading loop with a pre-formatted string.
    assert captured_executor_tg and captured_executor_tg[0] is None
    # trading loop called tg_cb at least once with a string message
    assert tg_cb.called
    call_arg = tg_cb.call_args[0][0]
    assert isinstance(call_arg, str)
    assert "TRADE" in call_arg or "Side" in call_arg


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
            db=_make_mock_db(),
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

    async def rotating_signals(markets, *, bankroll, alpha_model=None, **kwargs):
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
        )
    # No assertion needed — completing without exception is the success condition


async def test_tl16_no_signals_no_execution():
    """TL-16: When generate_signals returns empty list no trade is attempted.

    Use a market with liquidity below the minimum threshold to guarantee
    no signals are generated (alpha injection cannot bypass the liquidity filter).
    """
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    execute_mock = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market(p_market=0.70, p_model=0.30, liquidity_usd=0.0)]),  # zero liquidity
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
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
            db=_make_mock_db(),
        )


# ── Pipeline Final Activation tests (FA-01 – FA-10) ──────────────────────────


@pytest.mark.asyncio
async def test_fa01_market_cache_get_called_per_signal():
    """FA-01: market_cache.get() is called once per executed signal (non-blocking)."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="fa01-s", market_id="fa01-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa01-t", signal_id="fa01-s", market_id="fa01-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.005, partial_fill=False,
    )

    mock_cache = MagicMock()
    mock_cache.get = MagicMock(return_value=None)

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa01-mkt")]),
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
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            stop_event=stop, db=_make_mock_db(), market_cache=mock_cache,
        )

    mock_cache.get.assert_called_once_with("fa01-mkt")


@pytest.mark.asyncio
async def test_fa02_market_cache_question_used_in_telegram_message():
    """FA-02: Human-readable question from cache appears in Telegram trade message."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult
    from projects.polymarket.polyquantbot.core.market.market_cache import MarketMeta

    sig = SignalResult(
        signal_id="fa02-s", market_id="fa02-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa02-t", signal_id="fa02-s", market_id="fa02-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.005, partial_fill=False,
    )
    meta = MarketMeta(
        market_id="fa02-mkt",
        question="Will ETH hit $10k by end of 2025?",
        outcomes=["YES", "NO"],
    )
    mock_cache = MagicMock()
    mock_cache.get = MagicMock(return_value=meta)

    tg_cb = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa02-mkt")]),
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
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            telegram_callback=tg_cb,
            stop_event=stop, db=_make_mock_db(), market_cache=mock_cache,
        )

    assert tg_cb.called
    trade_msg = tg_cb.call_args[0][0]
    assert "ETH hit $10k" in trade_msg


@pytest.mark.asyncio
async def test_fa03_position_manager_open_called_on_fill():
    """FA-03: position_manager.open() is called after a successful trade fill."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="fa03-s", market_id="fa03-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa03-t", signal_id="fa03-s", market_id="fa03-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.005, partial_fill=False,
    )

    mock_pm = MagicMock()
    from projects.polymarket.polyquantbot.core.portfolio.position_manager import Position
    mock_pm.open = MagicMock(return_value=Position(
        market_id="fa03-mkt", side="YES", avg_price=0.40, size=50.0
    ))
    mock_pm.unrealized_pnl = MagicMock(return_value=0.0)
    mock_pm.all_positions = MagicMock(return_value=[])

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa03-mkt")]),
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
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            stop_event=stop, db=_make_mock_db(), position_manager=mock_pm,
        )

    mock_pm.open.assert_called_once_with(
        market_id="fa03-mkt",
        side="YES",
        fill_price=0.40,
        fill_size=50.0,
        trade_id="fa03-t",
    )


@pytest.mark.asyncio
async def test_fa04_pnl_tracker_record_unrealized_called():
    """FA-04: pnl_tracker.record_unrealized() is called after a successful fill."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult
    from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLRecord

    sig = SignalResult(
        signal_id="fa04-s", market_id="fa04-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa04-t", signal_id="fa04-s", market_id="fa04-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.005, partial_fill=False,
    )
    mock_pnl = MagicMock()
    mock_pnl.record_unrealized = MagicMock(
        return_value=PnLRecord(market_id="fa04-mkt", realized=0.0, unrealized=0.0)
    )
    mock_pnl.record_realized = MagicMock()

    mock_pm = MagicMock()
    from projects.polymarket.polyquantbot.core.portfolio.position_manager import Position
    mock_pm.open = MagicMock(return_value=Position(
        market_id="fa04-mkt", side="YES", avg_price=0.40, size=50.0
    ))
    mock_pm.unrealized_pnl = MagicMock(return_value=2.5)
    mock_pm.all_positions = MagicMock(return_value=[])

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa04-mkt")]),
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
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            stop_event=stop, db=_make_mock_db(),
            position_manager=mock_pm, pnl_tracker=mock_pnl,
        )

    mock_pnl.record_unrealized.assert_called_with("fa04-mkt", 2.5)


@pytest.mark.asyncio
async def test_fa05_pnl_in_telegram_message():
    """FA-05: realized_pnl and unrealized_pnl appear in the Telegram trade message."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult
    from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLRecord
    from projects.polymarket.polyquantbot.core.portfolio.position_manager import Position

    sig = SignalResult(
        signal_id="fa05-s", market_id="fa05-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa05-t", signal_id="fa05-s", market_id="fa05-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.008, partial_fill=False,
    )

    mock_pm = MagicMock()
    mock_pm.open = MagicMock(return_value=Position(
        market_id="fa05-mkt", side="YES", avg_price=0.40, size=50.0
    ))
    mock_pm.unrealized_pnl = MagicMock(return_value=-1.5)  # negative unrealized
    mock_pm.all_positions = MagicMock(return_value=[])

    mock_pnl = MagicMock()
    mock_pnl.record_unrealized = MagicMock(
        return_value=PnLRecord(market_id="fa05-mkt", realized=5.0, unrealized=-1.5)
    )

    tg_cb = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa05-mkt")]),
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
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            telegram_callback=tg_cb, stop_event=stop, db=_make_mock_db(),
            position_manager=mock_pm, pnl_tracker=mock_pnl,
        )

    assert tg_cb.called
    trade_msg = tg_cb.call_args[0][0]
    assert "Realized PnL" in trade_msg
    assert "Unrealized PnL" in trade_msg
    assert "$5.00" in trade_msg   # realized
    assert "$-1.50" in trade_msg  # negative unrealized


@pytest.mark.asyncio
async def test_fa06_no_crash_when_market_cache_missing_metadata():
    """FA-06: Loop does not crash when market_cache returns None (no metadata)."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="fa06-s", market_id="fa06-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa06-t", signal_id="fa06-s", market_id="fa06-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.0, partial_fill=False,
    )

    mock_cache = MagicMock()
    mock_cache.get = MagicMock(return_value=None)  # no metadata
    tg_cb = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa06-mkt")]),
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
        # Must not raise
        await run_trading_loop(
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            telegram_callback=tg_cb, stop_event=stop, db=_make_mock_db(),
            market_cache=mock_cache,
        )

    # Telegram still called, market_id used as fallback
    assert tg_cb.called
    msg = tg_cb.call_args[0][0]
    assert "fa06-mkt" in msg


@pytest.mark.asyncio
async def test_fa07_position_manager_failure_does_not_crash():
    """FA-07: Exception in position_manager.open() is caught; loop continues."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="fa07-s", market_id="fa07-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa07-t", signal_id="fa07-s", market_id="fa07-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.0, partial_fill=False,
    )

    mock_pm = MagicMock()
    mock_pm.open = MagicMock(side_effect=ValueError("side conflict"))
    mock_pm.all_positions = MagicMock(return_value=[])

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa07-mkt")]),
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
        # Must not raise
        await run_trading_loop(
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            stop_event=stop, db=_make_mock_db(), position_manager=mock_pm,
        )


@pytest.mark.asyncio
async def test_fa08_pnl_tracker_failure_does_not_crash():
    """FA-08: Exception in pnl_tracker.record_unrealized() is caught; loop continues."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult
    from projects.polymarket.polyquantbot.core.portfolio.position_manager import Position

    sig = SignalResult(
        signal_id="fa08-s", market_id="fa08-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa08-t", signal_id="fa08-s", market_id="fa08-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.0, partial_fill=False,
    )

    mock_pm = MagicMock()
    mock_pm.open = MagicMock(return_value=Position(
        market_id="fa08-mkt", side="YES", avg_price=0.40, size=50.0
    ))
    mock_pm.unrealized_pnl = MagicMock(return_value=0.0)
    mock_pm.all_positions = MagicMock(return_value=[])

    mock_pnl = MagicMock()
    mock_pnl.record_unrealized = MagicMock(side_effect=RuntimeError("db error"))

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa08-mkt")]),
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
        # Must not raise
        await run_trading_loop(
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            stop_event=stop, db=_make_mock_db(),
            position_manager=mock_pm, pnl_tracker=mock_pnl,
        )


@pytest.mark.asyncio
async def test_fa09_slippage_in_telegram_message():
    """FA-09: slippage_pct is formatted in the Telegram trade message."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="fa09-s", market_id="fa09-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=50.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa09-t", signal_id="fa09-s", market_id="fa09-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=50.0,
        filled_size_usd=50.0, fill_price=0.40, slippage_pct=0.012, partial_fill=False,
    )

    tg_cb = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa09-mkt")]),
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
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            telegram_callback=tg_cb, stop_event=stop, db=_make_mock_db(),
        )

    assert tg_cb.called
    msg = tg_cb.call_args[0][0]
    assert "Slippage" in msg
    assert "1.20%" in msg


@pytest.mark.asyncio
async def test_fa10_partial_fill_shown_in_telegram_message():
    """FA-10: partial fill info is shown in the Telegram trade message."""
    stop = asyncio.Event()

    async def fake_sleep(s):
        stop.set()

    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    from projects.polymarket.polyquantbot.core.execution.executor import TradeResult

    sig = SignalResult(
        signal_id="fa10-s", market_id="fa10-mkt", side="YES",
        p_market=0.40, p_model=0.65, edge=0.25, ev=0.5,
        kelly_f=0.25, size_usd=100.0, liquidity_usd=50_000.0,
    )
    trade_result = TradeResult(
        trade_id="fa10-t", signal_id="fa10-s", market_id="fa10-mkt",
        side="YES", success=True, mode="PAPER", attempted_size=100.0,
        filled_size_usd=70.0, fill_price=0.40, slippage_pct=0.0, partial_fill=True,
    )

    tg_cb = AsyncMock()

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[_market("fa10-mkt")]),
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
            loop_interval_s=0, bankroll=1000.0, mode="PAPER",
            telegram_callback=tg_cb, stop_event=stop, db=_make_mock_db(),
        )

    assert tg_cb.called
    msg = tg_cb.call_args[0][0]
    assert "partial" in msg.lower()
    assert "$70.00" in msg
