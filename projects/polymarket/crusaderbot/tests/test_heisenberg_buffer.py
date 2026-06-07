"""Hermetic tests for the in-memory Heisenberg real-time trade buffer.

No DB, no HTTP. Covers record/dedup/prune, the size cap, and the two read
shapes (per-market + per-wallet) that back Sharp Money and the copy-trade
fast-track after the durable heisenberg_realtime_trades table was dropped.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from projects.polymarket.crusaderbot.services import heisenberg_buffer as buf
from projects.polymarket.crusaderbot.services.heisenberg_trades import RealtimeTrade


def _tr(wallet, cid, side, size, *, minutes_ago=1, raw=None):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return RealtimeTrade(
        wallet=wallet, condition_id=cid, side=side, price=0.5,
        size_usdc=size, trade_time=ts, raw=raw or {},
    )


def setup_function(_):
    buf.clear()


def test_record_returns_count_and_dedups_by_key():
    n = buf.record_trades([_tr("0xA", "c1", "YES", 10.0), _tr("0xB", "c2", "NO", 5.0)])
    assert n == 2
    assert buf.size() == 2
    # Re-recording the SAME key (wallet/cid/time/side) upserts, not appends.
    ts = datetime.now(timezone.utc) - timedelta(minutes=5)  # within 24h retention
    first = RealtimeTrade("0xZ", "c9", "YES", 0.5, 10.0, ts, {})
    again = RealtimeTrade("0xZ", "c9", "YES", 0.5, 99.0, ts, {})  # same key, new size
    assert buf.record_trades([first]) == 1
    assert buf.record_trades([again]) == 1  # ingest count is per-call
    rows = buf.trades_for_markets(["c9"], datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert len(rows) == 1 and rows[0].size_usdc == 99.0  # overwritten, not duplicated


def test_prune_drops_entries_older_than_retention():
    buf.record_trades([
        _tr("0xA", "c1", "YES", 10.0, minutes_ago=30),       # fresh
        _tr("0xB", "c1", "YES", 10.0, minutes_ago=60 * 48),  # 48h old
    ], retention_hours=24)
    assert buf.size() == 1  # the 48h-old trade pruned


def test_trades_for_markets_filters_by_cid_and_window():
    buf.record_trades([
        _tr("0xA", "c1", "YES", 10.0, minutes_ago=5),
        _tr("0xA", "c2", "YES", 10.0, minutes_ago=5),
        _tr("0xA", "c1", "NO", 10.0, minutes_ago=60 * 30),  # outside a 24h window
    ])
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    got = buf.trades_for_markets(["c1"], since)
    assert len(got) == 1 and got[0].condition_id == "c1" and got[0].side == "YES"
    assert buf.trades_for_markets([], since) == []


def test_trades_for_wallet_lowercases_and_orders_ascending():
    buf.record_trades([
        _tr("0xABC", "c1", "YES", 1.0, minutes_ago=2),
        _tr("0xabc", "c2", "NO", 1.0, minutes_ago=10),
        _tr("0xDEF", "c1", "YES", 1.0, minutes_ago=1),
    ])
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    # Mixed-case query still matches lowercase-stored wallets.
    got = buf.trades_for_wallet("0xAbC", since)
    assert len(got) == 2
    assert got[0].trade_time < got[1].trade_time  # oldest first


def test_record_tolerates_naive_trade_time():
    naive = RealtimeTrade(
        wallet="0xA", condition_id="c1", side="YES", price=0.5, size_usdc=10.0,
        trade_time=datetime.utcnow(),  # naive
        raw={},
    )
    assert buf.record_trades([naive]) == 1
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    assert len(buf.trades_for_markets(["c1"], since)) == 1
