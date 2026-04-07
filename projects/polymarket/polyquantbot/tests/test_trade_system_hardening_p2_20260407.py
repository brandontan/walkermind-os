from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.execution import engine_router


class _FailingWallet:
    async def restore_from_db(self, db: object) -> None:
        raise RuntimeError("wallet restore broke")


class _OkPositions:
    async def load_from_db(self, db: object) -> None:
        return None


class _OkLedger:
    async def load_from_db(self, db: object) -> None:
        return None


class _CaptureLog:
    def __init__(self) -> None:
        self.warning_events: list[tuple[str, dict[str, object]]] = []
        self.info_events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.warning_events.append((event, kwargs))

    def info(self, event: str, **kwargs: object) -> None:
        self.info_events.append((event, kwargs))


def test_restore_failure_emits_explicit_restore_failure_outcome() -> None:
    container = engine_router.EngineContainer()
    container.wallet = _FailingWallet()  # type: ignore[assignment]
    container.positions = _OkPositions()  # type: ignore[assignment]
    container.ledger = _OkLedger()  # type: ignore[assignment]

    capture_log = _CaptureLog()
    original_log = engine_router.log
    engine_router.log = capture_log  # type: ignore[assignment]
    try:
        asyncio.run(container.restore_from_db(db=object()))
    finally:
        engine_router.log = original_log

    restore_outcomes = [
        payload
        for event, payload in capture_log.warning_events
        if event == "engine_container_restore_outcome"
    ]
    assert restore_outcomes, "restore outcome warning was not emitted"
    assert restore_outcomes[0]["outcome"] == "restore_failure"
    assert restore_outcomes[0]["failed_components"] == ["wallet"]
