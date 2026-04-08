from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.strategy.strategy_manager import StrategyStateManager
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter
from projects.polymarket.polyquantbot.telegram.ui.keyboard import build_strategy_menu


def _make_router(*, strategy_state: StrategyStateManager, db: object | None = None) -> CallbackRouter:
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
        strategy_state=strategy_state,
        db=db,
    )


class TestTelegramEVMomentumTogglePersistence:
    def test_ev_momentum_toggle_on_persists_after_callback(self) -> None:
        strategy_state = StrategyStateManager(initial_state={"ev_momentum": False})
        db = AsyncMock()
        db.save_strategy_state = AsyncMock(return_value=True)
        router = _make_router(strategy_state=strategy_state, db=db)

        asyncio.run(router._dispatch("strategy_toggle:ev_momentum"))

        assert strategy_state.get_state()["ev_momentum"] is True
        db.save_strategy_state.assert_called_once()
        persisted = db.save_strategy_state.call_args.args[0]
        assert persisted["ev_momentum"] is True

    def test_menu_rerender_reads_persisted_ev_momentum_active_state(self) -> None:
        strategy_state = StrategyStateManager(initial_state={"ev_momentum": False})
        db = AsyncMock()
        db.save_strategy_state = AsyncMock(return_value=True)
        router = _make_router(strategy_state=strategy_state, db=db)

        asyncio.run(router._dispatch("strategy_toggle:ev_momentum"))
        text, _ = asyncio.run(router._dispatch("settings_strategy"))

        assert "EV MOMENTUM" in text
        assert "Status: ✅ ACTIVE" in text

    def test_ev_momentum_toggle_off_then_on_is_deterministic(self) -> None:
        strategy_state = StrategyStateManager(initial_state={"ev_momentum": True})
        db = AsyncMock()
        db.save_strategy_state = AsyncMock(return_value=True)
        router = _make_router(strategy_state=strategy_state, db=db)

        asyncio.run(router._dispatch("strategy_toggle:ev_momentum"))
        assert strategy_state.get_state()["ev_momentum"] is False

        asyncio.run(router._dispatch("strategy_toggle:ev_momentum"))
        assert strategy_state.get_state()["ev_momentum"] is True

        persisted_states = [call.args[0]["ev_momentum"] for call in db.save_strategy_state.call_args_list]
        assert persisted_states == [False, True]

    def test_other_strategy_toggles_remain_intact(self) -> None:
        strategy_state = StrategyStateManager(
            initial_state={"ev_momentum": True, "mean_reversion": True, "liquidity_edge": True}
        )
        db = AsyncMock()
        db.save_strategy_state = AsyncMock(return_value=True)
        router = _make_router(strategy_state=strategy_state, db=db)

        callbacks = [
            btn["callback_data"]
            for row in build_strategy_menu(["ev_momentum", "mean_reversion", "liquidity_edge"])
            for btn in row
        ]
        assert "action:strategy_toggle:ev_momentum" in callbacks

        asyncio.run(router._dispatch("strategy_toggle:mean_reversion"))

        current = strategy_state.get_state()
        assert current["ev_momentum"] is True
        assert current["mean_reversion"] is False
        assert current["liquidity_edge"] is True
