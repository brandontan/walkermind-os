from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter
from projects.polymarket.polyquantbot.telegram.command_handler import CommandResult
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager


class _StubCommandRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def route_structured(self, payload: dict) -> CommandResult:
        self.calls.append(payload)
        return CommandResult(success=True, message="ok", payload={"status": "executed"})


def test_callback_trade_routes_through_command_parser() -> None:
    async def _run() -> None:
        stub_router = _StubCommandRouter()
        callback_router = CallbackRouter(
            tg_api="https://api.telegram.org/botTEST",
            cmd_handler=object(),
            command_router=stub_router,
            state_manager=SystemStateManager(),
            config_manager=ConfigManager(),
            mode="PAPER",
        )

        callback_router._build_normalized_payload = lambda _action: {  # type: ignore[method-assign]
            "market_id": "MARKET-1",
            "side": "YES",
            "size": 10.0,
        }

        text, _keyboard = await callback_router._dispatch("trade_paper_execute")
        assert text == "ok"
        assert len(stub_router.calls) == 1
        assert stub_router.calls[0]["command"] == "trade"
        assert str(stub_router.calls[0]["raw_args"]).startswith("test MARKET-1 YES 10.00")

    asyncio.run(_run())
