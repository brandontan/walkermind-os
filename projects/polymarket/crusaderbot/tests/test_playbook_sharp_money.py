"""PLAYBOOK Phase-2b — Sharp Money (native) unit tests.

Covers the now-live ``SharpMoneyModule`` claim logic (TTL>24h gate, flow floor,
confidence floor, side from imbalance sign), router precedence (sharp_money
fires ahead of closing_edge far from the event without disturbing closing_edge
near it), and the DB-backed ``fetch_sharp_flows`` source (aggregation, batched
query shape, fail-soft, zero-flow skip). Hermetic — no DB, no network.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from projects.polymarket.crusaderbot.domain.playbook import sharp_flow as SF
from projects.polymarket.crusaderbot.domain.playbook.modules import (
    ClosingEdgeModule,
    MarketSnapshot,
    SharpMoneyModule,
)
from projects.polymarket.crusaderbot.domain.playbook.router import PlaybookRouter
from projects.polymarket.crusaderbot.domain.playbook.signals import (
    SHARP_MONEY,
    compute_signal_bundle,
)

_FAR_TTL = 172_800.0  # 48h — outside the 24h Sharp Money gate
_NEAR_TTL = 600.0     # 10m — Closing Edge window


def _snapshot(*, signed: float, total: float, ttl: float = _FAR_TTL, **over) -> MarketSnapshot:
    base = dict(
        market_id="m1", condition_id="c1", sport="MLB",
        fair_price=0.60, yes_ask=0.55, no_ask=0.46,
        seconds_to_event=ttl, liquidity_usdc=20_000.0, suggested_size_usdc=20.0,
        cluster_key="mlb:nyy@bos",
        sharp_signed_usdc=signed, sharp_total_flow_usdc=total,
    )
    base.update(over)
    return MarketSnapshot(**base)


def _bundle(snap: MarketSnapshot):
    return compute_signal_bundle(
        market_id=snap.market_id, mid_now=snap.fair_price, mid_prev=snap.fair_price,
        noise_sigma=0.05, liquidity_usdc=snap.liquidity_usdc, spread=0.03,
        seconds_to_event=snap.seconds_to_event, close_window_sec=1_800.0,
        buy_flow_usdc=0.0, sell_flow_usdc=0.0,
        sharp_signed_usdc=snap.sharp_signed_usdc,
        total_flow_usdc=snap.sharp_total_flow_usdc,
    )


# ── module claim logic ────────────────────────────────────────────────────
def test_sharp_money_claims_yes_on_positive_imbalance():
    snap = _snapshot(signed=8_000.0, total=10_000.0)
    d = SharpMoneyModule().evaluate(snap, _bundle(snap))
    assert d.claimed and d.side == "YES"
    assert 0.0 < d.confidence <= 1.0
    assert d.metadata["module"] == "sharp_money"
    assert d.metadata["sharp_imbalance"] == 0.8


def test_sharp_money_claims_no_on_negative_imbalance():
    snap = _snapshot(signed=-7_000.0, total=10_000.0)
    d = SharpMoneyModule().evaluate(snap, _bundle(snap))
    assert d.claimed and d.side == "NO"


def test_sharp_money_no_claim_inside_24h_window():
    snap = _snapshot(signed=8_000.0, total=10_000.0, ttl=_NEAR_TTL)
    d = SharpMoneyModule().evaluate(snap, _bundle(snap))
    assert not d.claimed and d.reasoning == "ttl_inside_24h_window"


def test_sharp_money_no_claim_below_flow_floor():
    snap = _snapshot(signed=300.0, total=400.0)  # < SHARP_MONEY_MIN_FLOW_USDC
    d = SharpMoneyModule().evaluate(snap, _bundle(snap))
    assert not d.claimed and d.reasoning == "sharp_flow_below_floor"


def test_sharp_money_no_claim_below_confidence():
    # imbalance 0.10 → confidence 0.10 < 0.20 min, with flow above the floor.
    snap = _snapshot(signed=1_000.0, total=10_000.0)
    d = SharpMoneyModule().evaluate(snap, _bundle(snap))
    assert not d.claimed and "below_min" in d.reasoning


def test_sharp_money_no_claim_when_no_flow_default():
    # Phase-1 backward-compat: default 0.0 flow → neutral reading → no claim.
    snap = _snapshot(signed=0.0, total=0.0)
    d = SharpMoneyModule().evaluate(snap, _bundle(snap))
    assert not d.claimed


# ── router precedence ─────────────────────────────────────────────────────
def test_router_routes_sharp_money_far_from_event():
    snap = _snapshot(signed=8_000.0, total=10_000.0, ttl=_FAR_TTL)
    res = PlaybookRouter().route(snap, _bundle(snap))
    assert res.routed and res.module == "sharp_money"


def test_router_closing_edge_unaffected_near_event():
    # Near event, no sharp flow → sharp_money abstains, closing_edge still claims.
    snap = _snapshot(signed=0.0, total=0.0, ttl=_NEAR_TTL)
    res = PlaybookRouter().route(snap, _bundle(snap))
    assert res.routed and res.module == "closing_edge"


def test_closing_edge_abstains_far_from_event():
    snap = _snapshot(signed=0.0, total=0.0, ttl=_FAR_TTL)
    d = ClosingEdgeModule().evaluate(snap, _bundle(snap))
    assert not d.claimed  # mutually exclusive TTL windows with sharp_money


# ── DB-backed source (fetch_sharp_flows) ──────────────────────────────────
class _Conn:
    def __init__(self, rows=None, raise_exc=False):
        self._rows = rows or []
        self._raise = raise_exc
        self.queries: list[str] = []
        self.args: list[tuple] = []

    async def fetch(self, sql, *a):
        self.queries.append(sql)
        self.args.append(a)
        if self._raise:
            raise RuntimeError("db down")
        return self._rows


class _Pool:
    def __init__(self, conn: _Conn):
        self._c = conn

    def acquire(self):
        c = self._c

        class _Ctx:
            async def __aenter__(self_inner):
                return c

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _patch(conn: _Conn):
    return patch.object(SF, "get_pool", return_value=_Pool(conn))


def test_fetch_sharp_flows_aggregates_and_scopes():
    conn = _Conn(rows=[{"condition_id": "c1", "signed_usdc": 8_000.0, "total_usdc": 10_000.0}])
    with _patch(conn):
        out = asyncio.run(SF.fetch_sharp_flows(["c1"]))
    assert out == {"c1": (8_000.0, 10_000.0)}
    q = conn.queries[0]
    assert "leaderboard_stats" in q and "win_rate" in q  # top-tier scoping pinned
    assert "heisenberg_realtime_trades" in q
    assert conn.args[0][0] == ["c1"]  # batched ANY($1)


def test_fetch_sharp_flows_empty_ids_skips_query():
    conn = _Conn()
    with _patch(conn):
        out = asyncio.run(SF.fetch_sharp_flows([]))
    assert out == {} and conn.queries == []


def test_fetch_sharp_flows_failsoft_on_error():
    conn = _Conn(raise_exc=True)
    with _patch(conn):
        out = asyncio.run(SF.fetch_sharp_flows(["c1"]))
    assert out == {}


def test_fetch_sharp_flows_skips_zero_total():
    conn = _Conn(rows=[{"condition_id": "c1", "signed_usdc": 0.0, "total_usdc": 0.0}])
    with _patch(conn):
        out = asyncio.run(SF.fetch_sharp_flows(["c1"]))
    assert out == {}
