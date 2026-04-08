from __future__ import annotations

from types import SimpleNamespace

from projects.polymarket.polyquantbot.core.pipeline.trading_loop import MarketScanPresenceNotifier
from projects.polymarket.polyquantbot.telegram.message_formatter import (
    format_market_scan_heartbeat,
    format_no_trade_explanation,
    format_top_candidate_preview,
)


def test_scan_heartbeat_emits_with_throttle_and_hierarchical_format() -> None:
    notifier = MarketScanPresenceNotifier()
    signals = [SimpleNamespace(market_id="MKT1", side="YES", edge=0.03)]

    first = notifier.build_messages(
        now_ts=1_000.0,
        tick=8,
        markets_scanned=42,
        signals=signals,
        trades_executed=0,
        no_trade_reason="insufficient edge",
    )
    assert any(message.startswith("🔎 MARKET SCAN") for message in first)

    second = notifier.build_messages(
        now_ts=1_020.0,
        tick=16,
        markets_scanned=42,
        signals=signals,
        trades_executed=0,
        no_trade_reason="insufficient edge",
    )
    assert not any(message.startswith("🔎 MARKET SCAN") for message in second)


def test_no_spam_on_repeated_cycle_same_reason() -> None:
    notifier = MarketScanPresenceNotifier()

    first = notifier.build_messages(
        now_ts=2_000.0,
        tick=1,
        markets_scanned=20,
        signals=[],
        trades_executed=0,
        no_trade_reason="insufficient edge",
    )
    assert first.count("⚠️ NO TRADE\n|- Reason: insufficient edge") == 1

    second = notifier.build_messages(
        now_ts=2_050.0,
        tick=2,
        markets_scanned=20,
        signals=[],
        trades_executed=0,
        no_trade_reason="insufficient edge",
    )
    assert "⚠️ NO TRADE\n|- Reason: insufficient edge" not in second


def test_top_candidate_preview_format_and_reason() -> None:
    notifier = MarketScanPresenceNotifier()
    signals = [
        SimpleNamespace(market_id="LOW", side="NO", edge=0.011),
        SimpleNamespace(market_id="HIGH", side="YES", edge=0.045),
    ]

    messages = notifier.build_messages(
        now_ts=3_000.0,
        tick=9,
        markets_scanned=55,
        signals=signals,
        trades_executed=0,
        no_trade_reason="insufficient edge",
    )

    candidate = [msg for msg in messages if msg.startswith("🧠 TOP CANDIDATE")]
    assert len(candidate) == 1
    lines = candidate[0].splitlines()
    assert lines == [
        "🧠 TOP CANDIDATE",
        "|- Market: HIGH",
        "|- Side: YES",
        "|- Edge: 4.50%",
        "|- Status: borderline",
        "|- Reason: edge below execution threshold",
    ]


def test_no_trade_explanation_only_when_no_trade_occurs() -> None:
    notifier = MarketScanPresenceNotifier()

    messages = notifier.build_messages(
        now_ts=4_000.0,
        tick=3,
        markets_scanned=12,
        signals=[SimpleNamespace(market_id="EXEC", side="YES", edge=0.08)],
        trades_executed=1,
        no_trade_reason="risk limit reached",
    )
    assert not any(msg.startswith("⚠️ NO TRADE") for msg in messages)


def test_formatter_hierarchy_spec_for_scan_presence_messages() -> None:
    heartbeat = format_market_scan_heartbeat(
        markets_scanned=50,
        active_candidates=2,
        status="Waiting for confirmation",
    )
    candidate = format_top_candidate_preview(
        market="MARKET-1",
        side="YES",
        edge_pct=3.25,
        status="waiting",
        reason="awaiting next confirmation",
    )
    no_trade = format_no_trade_explanation(reason="liquidity too low")

    for message in (heartbeat, candidate, no_trade):
        body = message.splitlines()[1:]
        assert body
        assert all(line.startswith("|-") for line in body)
