from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine, export_execution_payload
from projects.polymarket.polyquantbot.execution.gateway import ExecutionGateway
from projects.polymarket.polyquantbot.interface import ui_formatter
from projects.polymarket.polyquantbot.interface.telegram.view_handler import render_view
from projects.polymarket.polyquantbot.core.risk.pre_trade_validator import PreTradeValidator
from projects.polymarket.polyquantbot.core.risk.risk_engine import RiskEngine


async def _empty_context(_: str) -> dict[str, str]:
    return {}


def _render_positions(payload: dict) -> str:
    original = ui_formatter.get_market_context
    ui_formatter.get_market_context = _empty_context
    try:
        return asyncio.run(render_view("positions", payload))
    finally:
        ui_formatter.get_market_context = original


def test_position_with_valid_title_renders_market_title() -> None:
    payload = {
        "positions": [
            {
                "market_id": "mkt-1",
                "market_title": "Will BTC close above $120k in 2026?",
                "side": "YES",
                "entry_price": 0.55,
                "size": 100.0,
                "unrealized_pnl": 6.5,
            }
        ]
    }

    output = _render_positions(payload)

    assert "Will BTC close above $120k in 2026?" in output
    assert "Untitled Market" not in output


def test_multiple_positions_render_all_titles() -> None:
    payload = {
        "positions": [
            {"market_id": "a", "market_title": "ETH > 6k?", "side": "YES", "entry_price": 0.42, "size": 80.0, "unrealized_pnl": 1.2},
            {"market_id": "b", "market_title": "SOL > 400?", "side": "NO", "entry_price": 0.38, "size": 60.0, "unrealized_pnl": -0.7},
            {"market_id": "c", "market_title": "AVAX > 150?", "side": "YES", "entry_price": 0.31, "size": 40.0, "unrealized_pnl": 0.3},
        ]
    }

    output = _render_positions(payload)

    assert output.count("🎯 Position") == 3
    assert "ETH > 6k?" in output
    assert "SOL > 400?" in output
    assert "AVAX > 150?" in output


def test_same_market_multiple_positions_keep_consistent_title() -> None:
    payload = {
        "positions": [
            {"market_id": "btc-2026", "market_title": "Will BTC close above $120k in 2026?", "side": "YES", "entry_price": 0.50, "size": 90.0, "unrealized_pnl": 1.0},
            {"market_id": "btc-2026", "market_title": "Will BTC close above $120k in 2026?", "side": "YES", "entry_price": 0.53, "size": 120.0, "unrealized_pnl": 2.0},
        ]
    }

    output = _render_positions(payload)

    assert output.count("Will BTC close above $120k in 2026?") >= 2
    assert "Untitled Market" not in output


def test_before_and_after_untitled_regression_proof() -> None:
    before_payload = {
        "positions": [
            {"market_id": "legacy-1", "side": "YES", "entry_price": 0.45, "size": 50.0, "unrealized_pnl": 0.0}
        ]
    }
    after_payload = {
        "positions": [
            {
                "market_id": "legacy-1",
                "market_question": "Will Fed cut rates in June?",
                "side": "YES",
                "entry_price": 0.45,
                "size": 50.0,
                "unrealized_pnl": 0.0,
            }
        ]
    }

    before_output = _render_positions(before_payload)
    after_output = _render_positions(after_payload)

    assert "Untitled Market" in before_output or "Market legacy-1" in before_output
    assert "Will Fed cut rates in June?" in after_output
    assert "Untitled Market" not in after_output


def test_rendering_is_deterministic_for_same_payload() -> None:
    payload = {
        "positions": [
            {"market_id": "det-1", "market_title": "Will CPI come under 2.5%?", "side": "NO", "entry_price": 0.41, "size": 77.0, "unrealized_pnl": 0.5}
        ],
        "positions_count": 1,
        "updated_at": "2026-04-09T10:00:00+00:00",
    }

    first = _render_positions(payload)
    second = _render_positions(payload)

    assert first == second


def test_execution_to_payload_preserves_market_title() -> None:
    async def _run() -> dict[str, object]:
        engine = ExecutionEngine(starting_equity=1_000.0)
        gateway = ExecutionGateway(
            engine=engine,
            pre_trade_validator=PreTradeValidator(),
            risk_engine=RiskEngine(),
        )
        await gateway.open_validated_position(
            market="mkt-exec-1",
            market_title="Will unemployment stay below 4% in Q3?",
            side="YES",
            price=0.49,
            size=50.0,
            signal_data={"expected_value": 0.10, "edge": 0.04, "liquidity_usd": 20_000.0},
            decision_data={"position_size": 50.0, "target_market_id": "mkt-exec-1", "strategy_source": "S1"},
            position_id="pos-1",
        )
        from projects.polymarket.polyquantbot.execution import engine as engine_module

        original = engine_module._engine_singleton
        engine_module._engine_singleton = engine
        try:
            return await export_execution_payload()
        finally:
            engine_module._engine_singleton = original

    payload = asyncio.run(_run())
    positions = payload.get("positions", [])

    assert isinstance(positions, list)
    assert positions
    row = positions[0]
    assert row["market_title"] == "Will unemployment stay below 4% in Q3?"
