"""Unit tests for the complete-set LIVE booking primitive (Lane 3B).

Hermetic: asyncpg Pool/Connection, the CLOB client, market-data, audit,
notifications and the kill switch are all replaced with in-memory fakes so the
two-leg FOK + auto-unwind state machine is exercised with no DB, broker, or
network. The FOK contract is binary per leg (matched | killed), so every branch
is driven by the sequence of fake ``post_order`` results.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import complete_set_exec as cse
from projects.polymarket.crusaderbot.domain.execution.live import (
    LivePostSubmitError,
    LivePreSubmitError,
)
from projects.polymarket.crusaderbot.domain.strategy.complete_set_arb import (
    CompleteSetQuote,
)

pytestmark = pytest.mark.asyncio


def _quote(*, shares: float = 100.0, yes_cost: float = 45.0, no_cost: float = 50.0) -> CompleteSetQuote:
    total = yes_cost + no_cost
    return CompleteSetQuote(
        market_id="m1", condition_id="c1", yes_token_id="ytok", no_token_id="ntok",
        fillable_shares=shares, yes_cost_usdc=yes_cost, no_cost_usdc=no_cost,
        avg_pair_cost=round(total / shares, 6) if shares else 0.0,
        gross_margin_usdc=round(shares - total, 6),
        net_margin_usdc=round(shares - total - 0.02 * shares, 6),
    )


def _book(ask: float | None = None, bid: float | None = None, size: float = 1000.0) -> dict:
    out: dict[str, list] = {"asks": [], "bids": []}
    if ask is not None:
        out["asks"] = [{"price": str(ask), "size": str(size)}]
    if bid is not None:
        out["bids"] = [{"price": str(bid), "size": str(size)}]
    return out


FILL = {"orderID": "ord-fill", "status": "matched"}
KILL = {"orderID": "", "status": "unmatched"}


class FakeConn:
    def __init__(self, *, existing: int = 0) -> None:
        self.existing = existing
        self.order_inserts: list[tuple] = []
        self.position_inserts: list[tuple] = []
        self.order_updates: list[tuple] = []
        self.paired_updates: list[tuple] = []
        self.ledger_inserts: list[tuple] = []
        self.wallet_updates: list[tuple] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "SELECT COUNT(*) FROM orders" in query:
            return self.existing
        return None

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        if "INSERT INTO orders" in query:
            self.order_inserts.append(args)
            return {"id": uuid4()}
        if "INSERT INTO positions" in query:
            self.position_inserts.append(args)
            return {"id": uuid4()}
        return None

    async def execute(self, query: str, *args: Any) -> str:
        if "UPDATE orders SET status" in query:
            self.order_updates.append(args)
        elif "UPDATE positions SET paired_position_id" in query:
            self.paired_updates.append(args)
        elif "INSERT INTO ledger" in query:
            self.ledger_inserts.append(args)
        elif "UPDATE wallets" in query:
            self.wallet_updates.append(args)
        return "OK"

    def transaction(self) -> "_Tx":
        return _Tx()


class _Tx:
    async def __aenter__(self) -> "_Tx":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _Acquire:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConn:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


class FakeClob:
    """Returns (or raises) a scripted sequence of post_order results."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[dict] = []

    async def post_order(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeMDC:
    async def __aenter__(self) -> "FakeMDC":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get_tick_size(self, _token: str) -> str:
        return "0.01"

    async def get_neg_risk(self, _token: str) -> bool:
        return False


@pytest.fixture
def halts() -> list:
    return []


@pytest.fixture
def alerts() -> list:
    return []


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch, halts, alerts):
    async def _noop(**_kwargs: Any) -> None:
        return None

    async def _noop_send(*_a: Any, **_k: Any) -> None:
        return None

    async def _set_active(**kwargs: Any) -> dict:
        halts.append(kwargs)
        return {"active": True}

    async def _notify_operator(text: str, *_a: Any, **_k: Any) -> None:
        alerts.append(text)

    monkeypatch.setattr(cse, "assert_live_guards", lambda *a, **k: None)
    monkeypatch.setattr(cse, "MarketDataClient", FakeMDC)
    monkeypatch.setattr(cse.audit, "write", _noop)
    monkeypatch.setattr(cse.notifications, "send", _noop_send)
    monkeypatch.setattr(cse.notifications, "notify_operator", _notify_operator)
    monkeypatch.setattr(cse.kill_switch, "set_active", _set_active)
    monkeypatch.setattr(cse, "get_settings", lambda: object())


def _use_conn(monkeypatch, conn: FakeConn) -> None:
    monkeypatch.setattr(cse, "get_pool", lambda: FakePool(conn))


async def _book_live(conn, clob, *, quote=None, yes_book=None, no_book=None):
    return await cse.book_complete_set_live(
        user_id=uuid4(), telegram_user_id=7, role="admin", trading_mode="live",
        quote=quote or _quote(), market_question="ETH up?",
        idempotency_key="set:k1",
        yes_book=yes_book if yes_book is not None else _book(ask=0.45, bid=0.44),
        no_book=no_book if no_book is not None else _book(ask=0.50, bid=0.49),
        active_preset="balanced", clob_client=clob,
    )


# --------------------------------------------------------------------------- #
# Happy path: both legs fill                                                   #
# --------------------------------------------------------------------------- #
async def test_both_legs_fill_books_linked_pair(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, FILL])
    res = await _book_live(conn, clob)
    assert res["status"] == "open" and res["mode"] == "live"
    assert res["yes_position_id"] and res["no_position_id"]
    # two BUY legs, both FOK
    assert len(clob.calls) == 2
    assert all(c["order_type"] == "FOK" and c["side"] == "BUY" for c in clob.calls)
    # 2 positions, cross-linked, 2 ledger debits
    assert len(conn.position_inserts) == 2
    assert len(conn.paired_updates) == 2
    a, b = conn.paired_updates
    assert a[0] == b[1] and b[0] == a[1]
    assert len(conn.ledger_inserts) == 2
    # both legs persisted as the held-to-settlement strategy
    assert all(args[6] == cse.COMPLETE_SET_STRATEGY for args in conn.position_inserts)


async def test_fok_buy_limits_respect_arb_budget(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, FILL])
    await _book_live(conn, clob)
    # yes ask 0.45 -> 0.46, no ask 0.50 -> 0.51; sum 0.97 < 1.0
    yes_call = clob.calls[0]
    no_call = clob.calls[1]
    assert yes_call["price"] == 0.46 and no_call["price"] == 0.51
    assert yes_call["price"] + no_call["price"] < 1.0


# --------------------------------------------------------------------------- #
# Leg 1 (YES) killed: clean abort, zero exposure                              #
# --------------------------------------------------------------------------- #
async def test_yes_killed_clean_abort_no_second_leg(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([KILL])  # only one call should ever happen
    res = await _book_live(conn, clob)
    assert res["status"] == "no_fill" and res["leg"] == "yes"
    assert len(clob.calls) == 1  # NO leg never submitted -> no naked exposure
    assert conn.position_inserts == []
    assert conn.ledger_inserts == []


# --------------------------------------------------------------------------- #
# Leg 2 (NO) killed: YES naked -> auto-unwind                                  #
# --------------------------------------------------------------------------- #
async def test_no_killed_unwinds_naked_yes(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, KILL, FILL])  # yes fill, no kill, unwind sell fill
    res = await _book_live(conn, clob)
    assert res["status"] == "unwound" and res["naked_leg"] == "yes"
    # 3rd call is the unwind SELL
    assert len(clob.calls) == 3
    assert clob.calls[2]["side"] == "SELL" and clob.calls[2]["order_type"] == "FOK"
    # flat: no open complete-set position; ledger debit (cost) + credit (proceeds)
    assert conn.position_inserts == []
    assert len(conn.ledger_inserts) == 2
    # a successful unwind does NOT halt trading
    assert halts == []


async def test_unwind_sell_price_crosses_bid_down(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, KILL, FILL])
    await _book_live(conn, clob, yes_book=_book(ask=0.45, bid=0.44))
    # yes bid 0.44 -> aggressive sell 0.43
    assert clob.calls[2]["price"] == 0.43


# --------------------------------------------------------------------------- #
# Unwind fails -> HALT + persist naked leg as force-exitable                   #
# --------------------------------------------------------------------------- #
async def test_unwind_killed_halts_and_persists_naked(monkeypatch, halts, alerts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, KILL, KILL])  # unwind SELL also killed
    res = await _book_live(conn, clob)
    assert res["status"] == "naked_halt" and res["naked_leg"] == "yes"
    # naked leg persisted as a tracked, force-exitable position (NOT held-to-settle)
    assert len(conn.position_inserts) == 1
    assert conn.position_inserts[0][6] == cse.COMPLETE_SET_NAKED_STRATEGY
    assert conn.position_inserts[0][6] != cse.COMPLETE_SET_STRATEGY
    # capital really left -> single debit, no credit
    assert len(conn.ledger_inserts) == 1
    # trading halted + operator paged
    assert halts and halts[0]["action"] == "pause"
    assert alerts and "NAKED LEG" in alerts[-1]


async def test_unwind_no_bid_depth_halts_without_extra_submit(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, KILL])  # no third call: book has no bids to sell into
    res = await _book_live(conn, clob, yes_book=_book(ask=0.45, bid=None))
    assert res["status"] == "naked_halt"
    assert len(clob.calls) == 2  # unwind not even attempted
    assert halts and halts[0]["action"] == "pause"
    assert conn.position_inserts[0][6] == cse.COMPLETE_SET_NAKED_STRATEGY


# --------------------------------------------------------------------------- #
# Ambiguous submits -> post-submit error, halt, no duplication                 #
# --------------------------------------------------------------------------- #
async def test_yes_ambiguous_halts_and_raises_postsubmit(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([RuntimeError("timeout")])
    with pytest.raises(LivePostSubmitError):
        await _book_live(conn, clob)
    assert len(clob.calls) == 1  # NO leg never sent
    assert conn.position_inserts == []
    assert halts and halts[0]["action"] == "pause"


async def test_no_ambiguous_after_yes_fill_no_unwind(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, RuntimeError("timeout")])
    with pytest.raises(LivePostSubmitError):
        await _book_live(conn, clob)
    # NO leg ambiguous -> do NOT auto-unwind (could over-sell); halt instead
    assert len(clob.calls) == 2
    assert halts and halts[0]["action"] == "pause"


# --------------------------------------------------------------------------- #
# Pre-submit guards: arb invariant, depth, idempotency, degenerate quote       #
# --------------------------------------------------------------------------- #
async def test_arb_invariant_rejects_non_riskless(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([])
    # yes ask 0.60 -> 0.61, no ask 0.45 -> 0.46; sum 1.07 >= 1.0 -> reject
    with pytest.raises(LivePreSubmitError, match="not riskless"):
        await _book_live(conn, clob, yes_book=_book(ask=0.60, bid=0.59),
                         no_book=_book(ask=0.45, bid=0.44))
    assert clob.calls == []


async def test_book_depth_insufficient_aborts(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([])
    # only 10 shares of depth for a 100-share quote -> abort pre-submit
    thin = _book(ask=0.45, bid=0.44, size=10.0)
    with pytest.raises(LivePreSubmitError, match="depth insufficient"):
        await _book_live(conn, clob, yes_book=thin)
    assert clob.calls == []


async def test_duplicate_skips_without_submit(monkeypatch) -> None:
    conn = FakeConn(existing=2)
    _use_conn(monkeypatch, conn)
    clob = FakeClob([])
    res = await _book_live(conn, clob)
    assert res["status"] == "duplicate"
    assert clob.calls == []
    assert conn.position_inserts == []


async def test_non_positive_shares_skipped(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([])
    res = await _book_live(conn, clob, quote=_quote(shares=0.0, yes_cost=0.0, no_cost=0.0))
    assert res["status"] == "skipped"
    assert clob.calls == []


async def test_guard_failure_aborts_before_any_submit(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([])

    def _raise(*_a: Any, **_k: Any) -> None:
        raise LivePreSubmitError("ENABLE_LIVE_TRADING=false")

    monkeypatch.setattr(cse, "assert_live_guards", _raise)
    with pytest.raises(LivePreSubmitError):
        await _book_live(conn, clob)
    assert clob.calls == []
    assert conn.order_inserts == []


async def test_metadata_snapshot_rides_booked_legs(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, FILL])
    await _book_live(conn, clob)
    for args in conn.position_inserts:
        meta = json.loads(args[9])  # strategy_metadata json is the 10th position arg
        assert meta["complete_set"] is True
        assert meta["condition_id"] == "c1"
        assert meta["yes_token_id"] == "ytok" and meta["no_token_id"] == "ntok"
