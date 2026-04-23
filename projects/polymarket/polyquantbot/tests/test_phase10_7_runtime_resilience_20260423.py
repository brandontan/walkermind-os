from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.polyquantbot.server.core.runtime import RuntimeState
from projects.polymarket.polyquantbot.server.main import (
    _start_database_runtime,
    _reset_runtime_state_for_startup,
    _shutdown_runtime_components,
    _shutdown_telegram_runtime,
)


@pytest.mark.asyncio
async def test_shutdown_runtime_components_cleans_active_components() -> None:
    class _RetryingCloseClient:
        close_calls = 0

        async def close(self) -> None:
            _RetryingCloseClient.close_calls += 1
            if _RetryingCloseClient.close_calls == 1:
                raise RuntimeError("transient_close_error")

    state = RuntimeState(
        ready=True,
        telegram_runtime_active=True,
        telegram_runtime_shutdown_complete=False,
        db_runtime_enabled=True,
        db_runtime_connected=True,
        db_runtime_healthcheck_ok=True,
        db_client=_RetryingCloseClient(),
    )
    state.telegram_runtime_task = asyncio.create_task(asyncio.sleep(10))

    await _shutdown_runtime_components(state=state)

    assert state.telegram_runtime_task is None
    assert state.telegram_runtime_active is False
    assert state.telegram_runtime_shutdown_complete is True
    assert state.db_client is None
    assert state.db_runtime_connected is False
    assert state.db_runtime_healthcheck_ok is False
    assert _RetryingCloseClient.close_calls == 2


@pytest.mark.asyncio
async def test_shutdown_telegram_cancel_error_is_recorded() -> None:
    async def _error_on_cancel() -> None:
        while True:
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise RuntimeError("telegram_cancel_failure")

    state = RuntimeState(telegram_runtime_active=True)
    state.telegram_runtime_task = asyncio.create_task(_error_on_cancel())
    await asyncio.sleep(0)

    await _shutdown_telegram_runtime(state=state, timeout_s=0.05)

    assert state.telegram_runtime_task is None
    assert state.telegram_runtime_active is False
    assert state.telegram_runtime_shutdown_complete is True
    assert state.telegram_runtime_last_error == "telegram_cancel_failure"


def test_reset_runtime_state_for_startup_clears_stale_failure_posture() -> None:
    state = RuntimeState(
        validation_errors=["old_error"],
        telegram_runtime_startup_complete=True,
        telegram_runtime_active=True,
        telegram_runtime_shutdown_complete=True,
        telegram_runtime_last_error="telegram_failed",
        db_runtime_connected=True,
        db_runtime_healthcheck_ok=True,
        db_runtime_last_error="db_failed",
        db_client=object(),
    )
    _reset_runtime_state_for_startup(state)

    assert state.validation_errors == []
    assert state.telegram_runtime_startup_complete is False
    assert state.telegram_runtime_active is False
    assert state.telegram_runtime_shutdown_complete is False
    assert state.telegram_runtime_last_error == ""
    assert state.db_runtime_connected is False
    assert state.db_runtime_healthcheck_ok is False
    assert state.db_runtime_last_error == ""
    assert state.db_client is None


def test_reset_runtime_state_emits_structured_startup_transition_log(monkeypatch) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **kwargs: object) -> None:
        captured.append((event, kwargs))

    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.log.info", _capture)
    state = RuntimeState()

    _reset_runtime_state_for_startup(state)

    assert captured
    event, payload = captured[-1]
    assert event == "crusaderbot_runtime_transition"
    assert payload["transition"] == "startup_reset"
    assert "monitoring" in payload


@pytest.mark.asyncio
async def test_shutdown_runtime_components_emits_structured_shutdown_transition_logs(monkeypatch) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **kwargs: object) -> None:
        captured.append((event, kwargs))

    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.log.info", _capture)
    state = RuntimeState()
    state.telegram_runtime_task = asyncio.create_task(asyncio.sleep(1))

    await _shutdown_runtime_components(state=state)

    transitions = [payload["transition"] for event, payload in captured if event == "crusaderbot_runtime_transition"]
    assert "shutdown_begin" in transitions
    assert "telegram_shutdown" in transitions
    assert "db_shutdown" in transitions
    assert "shutdown_complete" in transitions


@pytest.mark.asyncio
async def test_db_dependency_failure_trace_is_structured_and_readable(monkeypatch) -> None:
    class _FailingDBClient:
        async def connect_with_retry(self, max_attempts: int = 4, base_backoff_s: float = 1.0) -> None:
            raise RuntimeError("db_connect_refused")

        async def healthcheck(self) -> bool:
            return False

        async def close(self) -> None:
            return None

    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **kwargs: object) -> None:
        captured.append((event, kwargs))

    monkeypatch.setenv("CRUSADER_DB_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_REQUIRED", "false")
    monkeypatch.setenv("DB_DSN", "postgresql://runtime:runtime@localhost:5432/runtime")
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.DatabaseClient", _FailingDBClient)
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.log.error", _capture)
    state = RuntimeState()

    await _start_database_runtime(state=state)

    assert state.dependency_failures_total == 1
    assert state.last_dependency_failure_surface == "db_runtime_startup"
    assert state.last_dependency_failure_error == "db_connect_refused"
    failure_logs = [
        payload
        for event, payload in captured
        if event == "crusaderbot_db_runtime_startup_failed"
    ]
    assert failure_logs
    assert failure_logs[-1]["failure_surface"] == "db_runtime_startup"
