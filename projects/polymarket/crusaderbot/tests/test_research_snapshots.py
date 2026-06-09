"""Phase-2c-2 — per-scan market snapshot recorder tests.

Covers the Gamma-dict field extraction (mid from bid/ask, lastTradePrice and
outcomePrices fallbacks, missing-key handling) and the fail-soft batched writer
(run_id prepend, non-dict skip, empty/error → 0). Hermetic — no DB, no network.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from projects.polymarket.crusaderbot.domain.research import snapshots as SNAP
from projects.polymarket.crusaderbot.domain.research.snapshots import (
    _extract,
    record_market_snapshots,
)

# row tuple = (market_id, category, best_bid, best_ask, mid, liquidity, raw_json)


def test_extract_mid_from_bid_ask():
    row = _extract({
        "conditionId": "c1", "bestBid": "0.4", "bestAsk": "0.6",
        "liquidity": "1000", "category": "Crypto",
    })
    assert row[0] == "c1" and row[1] == "Crypto"
    assert row[2] == 0.4 and row[3] == 0.6 and row[4] == 0.5 and row[5] == 1000.0


def test_extract_mid_fallback_last_trade():
    row = _extract({"id": "c2", "lastTradePrice": "0.55"})
    assert row[0] == "c2" and row[4] == 0.55 and row[2] is None and row[3] is None


def test_extract_mid_fallback_outcome_prices_json():
    row = _extract({"conditionId": "c3", "outcomePrices": '["0.7","0.3"]'})
    assert row[4] == 0.7


def test_extract_liquidity_num_fallback():
    row = _extract({"conditionId": "c4", "liquidityNum": 250.0})
    assert row[5] == 250.0


def test_extract_none_without_market_id():
    assert _extract({"bestBid": "0.5"}) is None


# ── fake pool/conn ────────────────────────────────────────────────────────
class _Conn:
    def __init__(self, *, raise_exc=False):
        self.raise_exc = raise_exc
        self.rows = None
        self.sql = ""

    async def executemany(self, sql, rows):
        self.sql = sql
        if self.raise_exc:
            raise RuntimeError("db down")
        self.rows = rows


class _Pool:
    def __init__(self, conn):
        self._c = conn

    def acquire(self):
        c = self._c

        class _Ctx:
            async def __aenter__(self_inner):
                return c

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _patch(conn):
    return patch.object(SNAP, "get_pool", return_value=_Pool(conn))


def test_record_empty_returns_zero():
    conn = _Conn()
    with _patch(conn):
        n = asyncio.run(record_market_snapshots("run1", []))
    assert n == 0 and conn.rows is None


def test_record_never_persists_warp82():
    """WARP-82: record_market_snapshots is a no-op (no durable storage).

    Even with valid markets, it returns 0 and never calls executemany — the
    real-time universe stays in-memory; the table is dropped in migration 087.
    """
    markets = [
        {"conditionId": "c1", "bestBid": "0.4", "bestAsk": "0.6"},
        {"id": "c2", "lastTradePrice": "0.5"},
    ]
    conn = _Conn()
    with _patch(conn):
        n = asyncio.run(record_market_snapshots("run1", markets))
    assert n == 0
    assert conn.rows is None and conn.sql == ""  # no DB write attempted
