from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


@pytest.fixture
def router() -> CallbackRouter:
    cmd_handler = MagicMock()
    cmd_handler._runner = None
    cmd_handler._multi_metrics = None
    cmd_handler._allocator = None
    cmd_handler._risk_guard = None
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd_handler,
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_trade_paper_execute_valid_path_triggers_execution(router: CallbackRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def _fake_execute_trade(signal, **kwargs):  # type: ignore[no-untyped-def]
        called["signal_id"] = signal.signal_id
        called["market_id"] = signal.market_id
        called["kwargs"] = kwargs

        class _Result:
            success = True
            reason = ""
            market_id = signal.market_id
            side = signal.side
            attempted_size = signal.size_usd
            filled_size_usd = signal.size_usd

        return _Result()

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.execution.executor.execute_trade",
        _fake_execute_trade,
    )

    text, _keyboard = asyncio.run(
        router._dispatch("trade_paper_execute|mkt-1|YES|0.49|100|sig-123", user_id=1)
    )

    assert "Paper execution submitted" in text
    assert called["signal_id"] == "sig-123"
    assert called["market_id"] == "mkt-1"


def test_trade_paper_execute_duplicate_click_blocked(router: CallbackRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0

    async def _fake_execute_trade(signal, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1

        class _Result:
            success = True
            reason = ""
            market_id = signal.market_id
            side = signal.side
            attempted_size = signal.size_usd
            filled_size_usd = signal.size_usd

        return _Result()

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.execution.executor.execute_trade",
        _fake_execute_trade,
    )

    action = "trade_paper_execute|mkt-1|YES|0.49|100|sig-dup"
    first_text, _ = asyncio.run(router._dispatch(action, user_id=1))
    second_text, _ = asyncio.run(router._dispatch(action, user_id=1))

    assert "Paper execution submitted" in first_text
    assert "Duplicate execute ignored" in second_text
    assert call_count == 1


def test_trade_paper_execute_rejects_malformed_payload(router: CallbackRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("execute_trade should not be called")

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.execution.executor.execute_trade",
        _boom,
    )

    text, _ = asyncio.run(router._dispatch("trade_paper_execute|broken", user_id=1))
    assert "Paper execution blocked" in text
    assert "Invalid execute payload" in text


def test_trade_paper_execute_failure_feedback_visible(router: CallbackRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_execute_trade(signal, **kwargs):  # type: ignore[no-untyped-def]
        class _Result:
            success = False
            reason = "kill_switch_active"
            market_id = signal.market_id
            side = signal.side
            attempted_size = signal.size_usd
            filled_size_usd = 0.0

        return _Result()

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.execution.executor.execute_trade",
        _fake_execute_trade,
    )

    text, _ = asyncio.run(
        router._dispatch("trade_paper_execute|mkt-2|NO|0.51|120|sig-fail", user_id=1)
    )
    assert "Paper execution blocked" in text
    assert "kill_switch_active" in text
