from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter
from projects.polymarket.polyquantbot.telegram.handlers.shared_execution_entry import (
    UnifiedTradeRequest,
    UnifiedTradeResult,
    execute_unified_trade_entry,
    parse_trade_payload,
)


@pytest.fixture(autouse=True)
def _reset_execution_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("projects.polymarket.polyquantbot.execution.engine._engine_singleton", None)


def test_command_trade_path_uses_unified_execution_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = CommandHandler(state_manager=SystemStateManager(), config_manager=ConfigManager())
    called: list[str] = []

    async def _fake_execute(request: UnifiedTradeRequest, source: str) -> UnifiedTradeResult:
        called.append(source)
        return UnifiedTradeResult(
            success=True,
            message="ok",
            payload={"positions": [], "cash": 0.0, "equity": 0.0, "realized": 0.0, "unrealized": 0.0},
        )

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.telegram.command_handler.execute_unified_trade_entry",
        _fake_execute,
    )

    result = asyncio.run(handler._handle_trade_test("market-a YES 25"))
    assert result.success is True
    assert called == ["command:/trade test"]


def test_callback_trade_path_uses_unified_execution_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    router = CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=MagicMock(),
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )
    called: list[str] = []

    async def _fake_execute(request: UnifiedTradeRequest, source: str) -> UnifiedTradeResult:
        called.append(source)
        return UnifiedTradeResult(
            success=True,
            message="ok",
            payload={"positions": [], "cash": 0.0, "equity": 0.0, "realized": 0.0, "unrealized": 0.0},
        )

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.telegram.handlers.callback_router.execute_unified_trade_entry",
        _fake_execute,
    )

    text, _ = asyncio.run(router._dispatch("trade_paper_execute"))
    assert "POSITIONS" in text.upper()
    assert called == ["callback:trade_paper_execute"]


def test_both_paths_hit_same_unified_function(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = CommandHandler(state_manager=SystemStateManager(), config_manager=ConfigManager())
    router = CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=MagicMock(),
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )

    async def _fake_execute(request: UnifiedTradeRequest, source: str) -> UnifiedTradeResult:
        return UnifiedTradeResult(
            success=True,
            message=source,
            payload={"positions": [], "cash": 0.0, "equity": 0.0, "realized": 0.0, "unrealized": 0.0},
        )

    cmd_mock = AsyncMock(side_effect=_fake_execute)
    cb_mock = AsyncMock(side_effect=_fake_execute)
    monkeypatch.setattr("projects.polymarket.polyquantbot.telegram.command_handler.execute_unified_trade_entry", cmd_mock)
    monkeypatch.setattr("projects.polymarket.polyquantbot.telegram.handlers.callback_router.execute_unified_trade_entry", cb_mock)

    asyncio.run(handler._handle_trade_test("market-b NO 10"))
    asyncio.run(router._dispatch("trade_paper_execute"))

    assert cmd_mock.await_count == 1
    assert cb_mock.await_count == 1
    assert cmd_mock.await_args.kwargs["request"].__class__ is UnifiedTradeRequest
    assert cb_mock.await_args.kwargs["request"].__class__ is UnifiedTradeRequest


def test_duplicate_protection_blocks_same_market_and_side() -> None:
    first = asyncio.run(
        execute_unified_trade_entry(
            request=UnifiedTradeRequest(market="dup-market", side="YES", size=20.0),
            source="command:/trade test",
        )
    )
    second = asyncio.run(
        execute_unified_trade_entry(
            request=UnifiedTradeRequest(market="dup-market", side="YES", size=20.0),
            source="callback:trade_paper_execute",
        )
    )

    assert first.success is True
    assert second.success is False
    assert "Duplicate trade blocked" in second.message


def test_invalid_payload_rejection() -> None:
    with pytest.raises(ValueError, match="size must be numeric"):
        parse_trade_payload({"market": "mkt-1", "side": "YES", "size": "bad"})


def test_failure_handling_returns_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom_open_position(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulated execution failure")

    engine = MagicMock()
    engine.snapshot = AsyncMock(return_value=SimpleNamespace(positions=[]))
    engine.open_position = AsyncMock(side_effect=_boom_open_position)

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.telegram.handlers.shared_execution_entry.get_execution_engine",
        lambda: engine,
    )

    result = asyncio.run(
        execute_unified_trade_entry(
            request=UnifiedTradeRequest(market="fail-market", side="YES", size=10.0),
            source="command:/trade test",
        )
    )

    assert result.success is False
    assert "Trade execution failed" in result.message
