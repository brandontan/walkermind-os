from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.interface import ui_formatter
from projects.polymarket.polyquantbot.interface.telegram.view_handler import render_view


async def _stub_context(_: str) -> dict[str, str]:
    return {}


def _render_positions(payload: dict) -> str:
    original = ui_formatter.get_market_context
    ui_formatter.get_market_context = _stub_context
    try:
        return asyncio.run(render_view("positions", payload))
    finally:
        ui_formatter.get_market_context = original


def test_positions_same_market_are_all_rendered() -> None:
    payload = {
        "positions": [
            {"market_id": "mkt-1", "market_question": "BTC > 100k?", "side": "YES", "entry_price": 0.45, "size": 100, "unrealized_pnl": 4.0},
            {"market_id": "mkt-1", "market_question": "BTC > 100k?", "side": "YES", "entry_price": 0.47, "size": 150, "unrealized_pnl": 6.0},
        ],
        "positions_count": 2,
        "unrealized_pnl": 10.0,
    }

    output = _render_positions(payload)

    assert "Open Positions: 2" in output
    assert output.count("🎯 Position") == 2
    assert "Size: $100.00" in output
    assert "Size: $150.00" in output


def test_positions_different_markets_are_all_rendered() -> None:
    payload = {
        "positions": [
            {"market_id": "mkt-a", "market_question": "ETH > 5k?", "side": "YES", "entry_price": 0.50, "size": 50, "unrealized_pnl": 1.5},
            {"market_id": "mkt-b", "market_question": "SOL > 300?", "side": "NO", "entry_price": 0.40, "size": 75, "unrealized_pnl": -0.5},
            {"market_id": "mkt-c", "market_question": "AVAX > 100?", "side": "YES", "entry_price": 0.35, "size": 90, "unrealized_pnl": 0.2},
        ],
    }

    output = _render_positions(payload)

    assert output.count("🎯 Position") == 3
    assert "ETH > 5k?" in output
    assert "SOL > 300?" in output
    assert "AVAX > 100?" in output


def test_summary_count_matches_rendered_position_count() -> None:
    payload = {
        "positions": [
            {"market_id": "mkt-1", "market_question": "Q1", "side": "YES", "entry_price": 0.10, "size": 10, "unrealized_pnl": 0.1},
            {"market_id": "mkt-2", "market_question": "Q2", "side": "YES", "entry_price": 0.20, "size": 20, "unrealized_pnl": 0.2},
            {"market_id": "mkt-3", "market_question": "Q3", "side": "NO", "entry_price": 0.30, "size": 30, "unrealized_pnl": -0.3},
        ],
        "positions_count": 1,
    }

    output = _render_positions(payload)

    assert "Open Positions: 3" in output
    assert output.count("🎯 Position") == 3


def test_similar_ids_do_not_overwrite_each_other() -> None:
    payload = {
        "positions": [
            {"market_id": "market-abc-001", "market_question": "Outcome A", "side": "YES", "entry_price": 0.42, "size": 42, "unrealized_pnl": 1.0},
            {"market_id": "market-abc-001-extra", "market_question": "Outcome B", "side": "YES", "entry_price": 0.43, "size": 43, "unrealized_pnl": 2.0},
        ],
    }

    output = _render_positions(payload)

    assert output.count("🎯 Position") == 2
    assert "Outcome A" in output
    assert "Outcome B" in output
