from __future__ import annotations

import asyncio
from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution import engine as execution_engine_module
from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine, export_execution_payload
from projects.polymarket.polyquantbot.interface import ui_formatter
from projects.polymarket.polyquantbot.interface.telegram.view_handler import render_view
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter
from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager


@dataclass(frozen=True)
class _PortfolioStateStub:
    positions: tuple[dict[str, object], ...]
    equity: float
    cash: float
    pnl: float


class _PortfolioServiceStub:
    def __init__(self, state: _PortfolioStateStub) -> None:
        self._state = state

    def get_state(self) -> _PortfolioStateStub:
        return self._state


def _make_router() -> CallbackRouter:
    command_handler = type("CommandHandlerStub", (), {"_runner": None, "_multi_metrics": None, "_allocator": None, "_risk_guard": None})()
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=command_handler,
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def _render_positions(payload: dict) -> str:
    return asyncio.run(render_view("positions", payload))


def test_execution_output_mapping_includes_market_title(monkeypatch) -> None:
    isolated_engine = ExecutionEngine(starting_equity=10_000.0)
    monkeypatch.setattr(execution_engine_module, "_engine_singleton", isolated_engine)

    asyncio.run(
        isolated_engine.open_position(
            market="mkt-ev-1",
            market_title="Will ETH close above $4,000 this week?",
            side="YES",
            price=0.45,
            size=100.0,
            position_id="tg1-1",
        )
    )

    payload = asyncio.run(export_execution_payload())

    assert payload["positions"][0]["market_id"] == "mkt-ev-1"
    assert payload["positions"][0]["market_title"] == "Will ETH close above $4,000 this week?"


def test_execution_open_position_backwards_compat_without_market_title(monkeypatch) -> None:
    isolated_engine = ExecutionEngine(starting_equity=10_000.0)
    monkeypatch.setattr(execution_engine_module, "_engine_singleton", isolated_engine)

    asyncio.run(
        isolated_engine.open_position(
            market="mkt-legacy-2",
            side="YES",
            price=0.44,
            size=75.0,
            position_id="tg1-legacy",
        )
    )

    payload = asyncio.run(export_execution_payload())

    assert payload["positions"][0]["market_id"] == "mkt-legacy-2"
    assert payload["positions"][0]["market_title"] == ""


def test_portfolio_payload_builder_keeps_market_title(monkeypatch) -> None:
    router = _make_router()
    portfolio_state = _PortfolioStateStub(
        positions=(
            {
                "market_id": "mkt-btc-1",
                "market_title": "Will BTC close above $100k this month?",
                "side": "YES",
                "entry_price": 0.52,
                "size": 150.0,
                "unrealized_pnl": 12.5,
            },
        ),
        equity=10_500.0,
        cash=9_000.0,
        pnl=12.5,
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.telegram.handlers.callback_router.get_portfolio_service",
        lambda: _PortfolioServiceStub(portfolio_state),
    )

    payload = router._build_normalized_payload("positions")

    assert payload["market_id"] == "mkt-btc-1"
    assert payload["market_title"] == "Will BTC close above $100k this month?"


def test_position_with_valid_title_displays_correctly() -> None:
    payload = {
        "positions": [
            {
                "market_id": "mkt-eth-1",
                "market_title": "Will ETH close above $4,000 this week?",
                "side": "YES",
                "entry_price": 0.45,
                "size": 100.0,
                "unrealized_pnl": 4.0,
            }
        ],
        "positions_count": 1,
    }

    output = _render_positions(payload)

    assert "Will ETH close above $4,000 this week?" in output
    assert "Untitled Market" not in output


def test_multiple_positions_show_correct_titles_consistently() -> None:
    payload = {
        "positions": [
            {
                "market_id": "mkt-btc-1",
                "market_title": "Will BTC close above $100k this month?",
                "side": "YES",
                "entry_price": 0.51,
                "size": 120.0,
                "unrealized_pnl": 2.5,
            },
            {
                "market_id": "mkt-btc-1",
                "market_title": "Will BTC close above $100k this month?",
                "side": "YES",
                "entry_price": 0.53,
                "size": 80.0,
                "unrealized_pnl": -1.0,
            },
            {
                "market_id": "mkt-sol-1",
                "market_title": "Will SOL close above $300 this month?",
                "side": "NO",
                "entry_price": 0.35,
                "size": 90.0,
                "unrealized_pnl": 1.2,
            },
        ],
        "positions_count": 3,
    }

    output = _render_positions(payload)

    assert output.count("🎯 Position") == 3
    assert output.count("Will BTC close above $100k this month?") >= 2
    assert "Will SOL close above $300 this month?" in output


def test_missing_title_falls_back_only_when_unresolvable(monkeypatch) -> None:
    async def _stub_market_context(market_id: str) -> dict[str, str]:
        if market_id == "mkt-resolve":
            return {"question": "Resolved from cache title"}
        return {}

    original_get_market_context = ui_formatter.get_market_context
    ui_formatter.get_market_context = _stub_market_context
    try:
        payload = {
            "positions": [
                {
                    "market_id": "mkt-resolve",
                    "market_title": "",
                    "side": "YES",
                    "entry_price": 0.5,
                    "size": 50.0,
                    "unrealized_pnl": 0.5,
                },
                {
                    "market_id": "mkt-missing",
                    "market_title": "",
                    "side": "NO",
                    "entry_price": 0.4,
                    "size": 40.0,
                    "unrealized_pnl": -0.5,
                },
            ]
        }

        output = _render_positions(payload)
    finally:
        ui_formatter.get_market_context = original_get_market_context

    assert "Resolved from cache title" in output
    assert output.count("Untitled Market") == 1


def test_no_regression_positions_summary_and_render_count() -> None:
    payload = {
        "positions": [
            {
                "market_id": "mkt-a",
                "market_title": "Market A",
                "side": "YES",
                "entry_price": 0.3,
                "size": 25.0,
                "unrealized_pnl": 0.1,
            },
            {
                "market_id": "mkt-b",
                "market_title": "Market B",
                "side": "NO",
                "entry_price": 0.7,
                "size": 35.0,
                "unrealized_pnl": -0.2,
            },
        ],
        "positions_count": 1,
    }

    output = _render_positions(payload)

    assert "Open Positions: 2" in output
    assert output.count("🎯 Position") == 2
