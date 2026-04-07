from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from projects.polymarket.polyquantbot.core.execution import executor
from projects.polymarket.polyquantbot.core.pipeline import trading_loop
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult


def _signal(signal_id: str = "sig-safety-1") -> SignalResult:
    return SignalResult(
        signal_id=signal_id,
        market_id="mkt-safety",
        side="YES",
        p_market=0.45,
        p_model=0.6,
        edge=0.15,
        ev=0.1,
        kelly_f=0.2,
        size_usd=50.0,
        liquidity_usd=50_000.0,
    )


@pytest.fixture(autouse=True)
def _reset_executor_state() -> None:
    executor.reset_state()
    yield
    executor.reset_state()


def test_execution_blocked_when_mode_not_live_for_real_executor() -> None:
    calls: list[dict[str, Any]] = []

    async def _run() -> executor.TradeResult:
        async def _live_executor(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"filled_size": 50.0, "fill_price": 0.45}

        return await executor.execute_trade(_signal(), mode="PAPER", executor_callback=_live_executor)

    result = asyncio.run(_run())
    assert result.success
    assert result.mode == "PAPER"
    assert calls == []


def test_execution_blocked_when_kill_switch_active() -> None:
    result = asyncio.run(executor.execute_trade(_signal(), mode="LIVE", kill_switch_active=True))
    assert not result.success
    assert result.reason == "kill_switch_active"


def test_execution_allowed_in_paper_mode_via_paper_engine_only() -> None:
    calls: list[dict[str, Any]] = []

    async def _run() -> executor.TradeResult:
        async def _paper_executor(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {
                "filled_size": kwargs["size_usd"],
                "fill_price": kwargs["price"],
                "partial_fill": False,
                "reason": "paper_engine_executed",
            }

        return await executor.execute_trade(
            _signal(),
            mode="PAPER",
            paper_executor_callback=_paper_executor,
        )

    result = asyncio.run(_run())
    assert result.success
    assert result.mode == "PAPER"
    assert len(calls) == 1


def test_execution_always_routed_through_executor() -> None:
    source = Path(trading_loop.__file__).read_text()
    assert "result = await execute_trade(" in source
    assert "paper_executor_callback=" in source
    assert "Bypass execute_trade() fill simulation." not in source


def test_audit_log_generated_for_every_execution_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    def _capture(event: str, **kwargs: Any) -> None:
        events.append(event)

    monkeypatch.setattr(executor.log, "info", _capture)
    asyncio.run(executor.execute_trade(_signal("sig-audit"), mode="PAPER"))
    assert "execution_audit" in events


def test_no_silent_failure_on_forced_exception_path(monkeypatch: pytest.MonkeyPatch) -> None:
    errors: list[str] = []

    def _capture_error(event: str, **kwargs: Any) -> None:
        errors.append(event)

    async def _boom(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("forced_exception")

    monkeypatch.setattr(executor.log, "error", _capture_error)

    result = asyncio.run(
        executor.execute_trade(
            _signal("sig-exception"),
            mode="PAPER",
            paper_executor_callback=_boom,
        )
    )

    assert not result.success
    assert "execution_exception" in result.reason
    assert "execution_error" in errors
