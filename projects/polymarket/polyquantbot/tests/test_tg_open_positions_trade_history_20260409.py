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


def test_multiple_open_positions_all_displayed_newest_first() -> None:
    payload = {
        "positions": [
            {
                "market_id": "mkt-1",
                "position_id": "pos-older",
                "market_title": "Will BTC close above 120k?",
                "side": "YES",
                "entry_price": 0.44,
                "current_price": 0.46,
                "size": 120.0,
                "unrealized_pnl": 2.4,
                "opened_at": "2026-04-09T09:58:00+00:00",
            },
            {
                "market_id": "mkt-2",
                "position_id": "pos-newer",
                "market_title": "Will ETH close above 6k?",
                "side": "NO",
                "entry_price": 0.55,
                "current_price": 0.50,
                "size": 80.0,
                "unrealized_pnl": 4.0,
                "opened_at": "2026-04-09T10:03:00+00:00",
            },
        ],
    }

    output = _render_positions(payload)

    assert output.count("🎯 Position") == 2
    assert output.find("Will ETH close above 6k?") < output.find("Will BTC close above 120k?")


def test_same_market_multiple_positions_kept_separate_with_refs() -> None:
    payload = {
        "positions": [
            {
                "market_id": "same-market",
                "position_id": "pos-a",
                "market_title": "Will SOL close above 300?",
                "side": "YES",
                "entry_price": 0.41,
                "current_price": 0.43,
                "size": 60.0,
                "unrealized_pnl": 1.2,
                "opened_at": "2026-04-09T10:00:00+00:00",
            },
            {
                "market_id": "same-market",
                "position_id": "pos-b",
                "market_title": "Will SOL close above 300?",
                "side": "NO",
                "entry_price": 0.52,
                "current_price": 0.49,
                "size": 75.0,
                "unrealized_pnl": 2.25,
                "opened_at": "2026-04-09T10:01:00+00:00",
            },
        ],
    }

    output = _render_positions(payload)

    assert output.count("🎯 Position") == 2
    assert "|- Ref: pos-a" in output
    assert "|- Ref: pos-b" in output
    assert "|- Entry: 41.00¢" in output
    assert "|- Entry: 52.00¢" in output


def test_closed_trades_appear_in_trade_history_newest_first() -> None:
    payload = {
        "positions": [],
        "closed_trades": [
            {
                "market_id": "hist-1",
                "position_id": "hist-pos-1",
                "market_title": "Will CPI print under 2.5%?",
                "side": "YES",
                "entry_price": 0.40,
                "exit_price": 0.55,
                "pnl": 15.0,
                "result": "WIN",
                "closed_at": "2026-04-09T09:45:00+00:00",
            },
            {
                "market_id": "hist-2",
                "position_id": "hist-pos-2",
                "market_title": "Will rate cut happen in June?",
                "side": "NO",
                "entry_price": 0.60,
                "exit_price": 0.52,
                "pnl": 8.0,
                "result": "WIN",
                "closed_at": "2026-04-09T10:05:00+00:00",
            },
        ],
    }

    output = _render_positions(payload)

    assert "📜 Trade History" in output
    assert output.count("🏁 Closed Trade") == 2
    assert output.find("Will rate cut happen in June?") < output.find("Will CPI print under 2.5%?")


def test_empty_state_for_open_positions_and_history() -> None:
    output = _render_positions({"positions": [], "closed_trades": []})

    assert "No open positions" in output
    assert "No trade history yet" in output


def test_strict_card_formatting_for_positions_and_history() -> None:
    payload = {
        "positions": [
            {
                "market_id": "fmt-open",
                "position_id": "fmt-ref-1",
                "market_title": "Will unemployment stay below 4%?",
                "side": "YES",
                "entry_price": 0.49,
                "current_price": 0.51,
                "size": 100.0,
                "unrealized_pnl": 2.0,
                "opened_at": "2026-04-09T10:11:00+00:00",
            }
        ],
        "closed_trades": [
            {
                "market_id": "fmt-closed",
                "position_id": "fmt-ref-2",
                "market_title": "Will GDP beat estimate?",
                "side": "NO",
                "entry_price": 0.58,
                "exit_price": 0.48,
                "pnl": 10.0,
                "result": "WIN",
                "closed_at": "2026-04-09T10:12:00+00:00",
            }
        ],
    }

    output = _render_positions(payload)

    assert "🎯 Position" in output
    assert "|- Market:" in output
    assert "|- Side:" in output
    assert "|- Entry:" in output
    assert "|- Now:" in output
    assert "|- Size:" in output
    assert "|- UPNL:" in output
    assert "|- Opened:" in output
    assert "|- Status:" in output
    assert "|- Ref:" in output

    assert "📜 Trade History" in output
    assert "🏁 Closed Trade" in output
    assert "|- Exit:" in output
    assert "|- PnL:" in output
    assert "|- Result:" in output
    assert "|- Closed:" in output


def test_trade_history_is_capped_for_performance_safety() -> None:
    closed_trades = []
    for i in range(12):
        closed_trades.append(
            {
                "market_id": f"hist-{i}",
                "position_id": f"hist-pos-{i}",
                "market_title": f"History {i}",
                "side": "YES" if i % 2 == 0 else "NO",
                "entry_price": 0.40,
                "exit_price": 0.45,
                "pnl": 5.0,
                "result": "WIN",
                "closed_at": f"2026-04-09T10:{i:02d}:00+00:00",
            }
        )

    output = _render_positions({"positions": [], "closed_trades": closed_trades})

    assert output.count("🏁 Closed Trade") == ui_formatter.TRADE_HISTORY_LIMIT
