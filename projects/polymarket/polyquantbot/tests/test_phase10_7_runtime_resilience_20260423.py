from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.polyquantbot.server.core.runtime import RuntimeState
from projects.polymarket.polyquantbot.server.main import (
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
