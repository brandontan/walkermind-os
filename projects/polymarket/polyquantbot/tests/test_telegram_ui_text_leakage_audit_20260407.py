from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.interface import ui_formatter
from projects.polymarket.polyquantbot.interface.telegram.view_handler import render_view


def test_market_label_fallback_does_not_leak_internal_ref() -> None:
    async def _stub_context(_: str) -> dict[str, str]:
        return {}

    original = ui_formatter.get_market_context
    ui_formatter.get_market_context = _stub_context
    try:
        output = asyncio.run(
            ui_formatter.render_dashboard(
                {
                    "mode": "market",
                    "market_id": "540816abcdef1234",
                    "market_title": None,
                    "market_question": None,
                }
            )
        )
    finally:
        ui_formatter.get_market_context = original

    assert "Untitled Market" in output
    assert "(ref" not in output.lower()
    assert "Untitled market (ref" not in output


def test_sparse_payload_avoids_raw_none_and_na_strings() -> None:
    output = asyncio.run(
        render_view(
            "markets",
            {
                "enabled_categories": [None, "", "N/A", "Politics"],
                "decision": "None",
                "insight": None,
                "scope_warning": "",
                "market_id": "None",
                "market_title": "N/A",
                "market_question": None,
            },
        )
    )

    assert "None" not in output
    assert "N/A" not in output
    assert output.strip()


def test_title_first_behavior_keeps_human_readable_market_title() -> None:
    output = asyncio.run(
        render_view(
            "market",
            {
                "market_id": "raw-internal-market-id-999",
                "market_title": "Will ETH close above $4,000 this week?",
            },
        )
    )

    assert "Will ETH close above $4,000 this week?" in output
    assert "Untitled Market" not in output


def test_wallet_view_still_renders_non_empty_output() -> None:
    output = asyncio.run(render_view("wallet", {}))
    assert output.strip()
    assert "💼 Wallet Snapshot" in output
