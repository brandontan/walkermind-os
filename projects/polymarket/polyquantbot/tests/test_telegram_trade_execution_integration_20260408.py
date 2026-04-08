from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _make_router() -> CallbackRouter:
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=MagicMock(),
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_trade_paper_execute_valid_payload_triggers_execution_entry() -> None:
    router = _make_router()
    engine = SimpleNamespace(
        execute_order=AsyncMock(
            return_value=SimpleNamespace(
                trade_id="tg-sig-1",
                status=SimpleNamespace(value="FILLED"),
                filled_size=100.0,
                reason="",
            )
        )
    )
    router.set_paper_engine(engine)

    text, _ = asyncio.run(router._dispatch("trade_paper_execute|mkt-1|YES|0.55|100|tg-sig-1|0.08|15000"))

    engine.execute_order.assert_awaited_once()
    assert "Triggered via execution entry" in text
    assert "FILLED" in text


def test_trade_paper_execute_duplicate_click_is_blocked() -> None:
    router = _make_router()
    engine = SimpleNamespace(
        execute_order=AsyncMock(
            return_value=SimpleNamespace(
                trade_id="tg-sig-dup",
                status=SimpleNamespace(value="FILLED"),
                filled_size=50.0,
                reason="",
            )
        )
    )
    router.set_paper_engine(engine)

    action = "trade_paper_execute|mkt-dup|NO|0.41|50|tg-sig-dup|0.05|12000"
    first_text, _ = asyncio.run(router._dispatch(action))
    second_text, _ = asyncio.run(router._dispatch(action))

    engine.execute_order.assert_awaited_once()
    assert "Triggered via execution entry" in first_text
    assert "Duplicate Blocked" in second_text


def test_trade_paper_execute_invalid_input_is_rejected_without_execution() -> None:
    router = _make_router()
    engine = SimpleNamespace(
        execute_order=AsyncMock(
            return_value=SimpleNamespace(
                trade_id="should-not-run",
                status=SimpleNamespace(value="FILLED"),
                filled_size=1.0,
                reason="",
            )
        )
    )
    router.set_paper_engine(engine)

    text, _ = asyncio.run(router._dispatch("trade_paper_execute|mkt-bad|MAYBE|0.5|10"))

    engine.execute_order.assert_not_awaited()
    assert "Rejected" in text
    assert "blocked" in text.lower()


def test_trade_paper_execute_failure_path_surfaces_error() -> None:
    router = _make_router()
    engine = SimpleNamespace(execute_order=AsyncMock(side_effect=RuntimeError("paper engine boom")))
    router.set_paper_engine(engine)

    text, _ = asyncio.run(router._dispatch("trade_paper_execute|mkt-err|YES|0.6|20|tg-sig-err|0.06|15000"))

    engine.execute_order.assert_awaited_once()
    assert "Failed" in text
    assert "paper engine boom" in text
