from __future__ import annotations

from projects.polymarket.polyquantbot.execution.event_logger import EventLogger
from projects.polymarket.polyquantbot.execution.trace_context import (
    clear_trace_id,
    generate_trace_id,
    get_trace_id,
    set_trace_id,
)


def test_trace_id_exists() -> None:
    clear_trace_id()
    trace_id = get_trace_id()

    assert isinstance(trace_id, str)
    assert trace_id


def test_trace_id_propagates() -> None:
    clear_trace_id()
    expected_trace_id = generate_trace_id()
    set_trace_id(expected_trace_id)

    assert get_trace_id() == expected_trace_id


def test_event_emitted_with_structured_fields() -> None:
    clear_trace_id()
    captured_events: list[dict[str, object]] = []
    logger = EventLogger(sink=captured_events.append)

    event = logger.emit_event(
        event_type="execution_attempt",
        component="execution.engine_router",
        outcome="success",
        payload={"trade_id": "trade-001"},
    )

    assert captured_events
    assert event == captured_events[0]
    assert event["trace_id"]
    assert event["event_type"] == "execution_attempt"
    assert event["component"] == "execution.engine_router"
    assert event["outcome"] == "success"
    assert "timestamp" in event
    assert event["payload"] == {"trade_id": "trade-001"}


def test_failure_emits_structured_event() -> None:
    clear_trace_id()
    captured_events: list[dict[str, object]] = []
    logger = EventLogger(sink=captured_events.append)

    event = logger.emit_failure(
        event_type="execution_attempt",
        component="execution.engine_router",
        payload={"reason": "capital_insufficient"},
    )

    assert captured_events
    assert event["trace_id"]
    assert event["event_type"] == "execution_attempt"
    assert event["component"] == "execution.engine_router"
    assert event["outcome"] == "failure"
    assert "timestamp" in event
    assert event["payload"] == {"reason": "capital_insufficient"}
