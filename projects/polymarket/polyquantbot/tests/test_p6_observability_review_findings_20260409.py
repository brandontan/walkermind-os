from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.execution.observability import (
    EVENT_OUTCOME,
    EVENT_STAGE,
    OUTCOME_BLOCKED,
    OUTCOME_EXECUTED,
    OUTCOME_FAILED,
    STAGE_RISK,
    classify_result,
)
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler


@pytest.mark.parametrize(
    ("success", "message", "expected"),
    [
        (False, "duplicate_blocked: trade intent already executed recently.", OUTCOME_BLOCKED),
        (True, "ok", OUTCOME_EXECUTED),
        (False, "Usage: /trade [test|close|status] [args]", OUTCOME_FAILED),
    ],
)
def test_classify_result_includes_explicit_blocked(success: bool, message: str, expected: str) -> None:
    classified = classify_result(success=success, message=message)
    assert classified.outcome == expected


def test_trade_emits_single_terminal_outcome_event() -> None:
    observed: list[dict[str, object]] = []
    handler = CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        observability_sink=observed.append,
    )

    result = asyncio.run(handler.handle(command="trade", value="invalid"))

    assert result.success is False
    terminal_events = [
        event for event in observed if event["event_type"] == EVENT_OUTCOME
    ]
    assert len(terminal_events) == 1


def test_trade_path_does_not_emit_redundant_risk_stage() -> None:
    observed: list[dict[str, object]] = []
    handler = CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        observability_sink=observed.append,
    )

    asyncio.run(handler.handle(command="trade", value="status"))

    risk_stage_events = [
        event for event in observed
        if event["event_type"] == EVENT_STAGE and event["stage"] == STAGE_RISK
    ]
    assert risk_stage_events == []


def test_success_and_error_paths_keep_expected_observability_events() -> None:
    observed: list[dict[str, object]] = []
    handler = CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        observability_sink=observed.append,
    )

    success_result = asyncio.run(handler.handle(command="trade", value="status"))
    error_result = asyncio.run(handler.handle(command="trade", value="bad"))

    assert success_result.success is True
    assert error_result.success is False

    stage_events = [event for event in observed if event["event_type"] == EVENT_STAGE]
    terminal_events = [event for event in observed if event["event_type"] == EVENT_OUTCOME]

    assert len(stage_events) == 4  # two stage events per /trade attempt
    assert len(terminal_events) == 2
    assert terminal_events[0]["outcome"] == OUTCOME_EXECUTED
    assert terminal_events[1]["outcome"] == OUTCOME_FAILED
