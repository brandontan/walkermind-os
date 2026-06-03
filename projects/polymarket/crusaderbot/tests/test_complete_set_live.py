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
from projects.polymarket.crusaderbot.integrations.clob import (
    ClobAuthError,
    ClobCircuitOpenError,
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
# Accepted-but-not-terminal (Polymarket marketable-order delay window): MUST be
# treated as ambiguous (halt + reconcile), never as a clean kill.
DELAYED = {"orderID": "ord-delayed", "status": "delayed"}


class FakeConn:
    def __init__(self, *, existing: int = 0, fail_position_insert: bool = False) -> None:
        self.existing = existing
        self.fail_position_insert = fail_position_insert
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
            if self.fail_position_insert:
                raise RuntimeError("simulated position insert failure")
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
    """Returns (or raises) a scripted sequence of post_order results.

    Optionally maps a broker ``order_id`` -> fills list so ``get_fills`` can model
    real on-chain fills for exact-fill reconciliation; an unknown id returns ``[]``
    (the booker then keeps its pre-submit book estimate).
    """

    def __init__(
        self,
        results: list[Any],
        *,
        fills: dict[str, list[dict]] | None = None,
        order_status: dict[str, list[dict]] | None = None,
    ) -> None:
        self._results = list(results)
        self.calls: list[dict] = []
        self._fills = dict(fills or {})
        # order_id -> successive get_order() statuses; the LAST entry sticks so a
        # 1-element list models "stays in this status across every poll".
        self._order_status = {k: list(v) for k, v in (order_status or {}).items()}

    async def post_order(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def get_fills(self, order_id: str) -> list[dict]:
        return list(self._fills.get(order_id, []))

    async def get_order(self, order_id: str) -> dict:
        seq = self._order_status.get(order_id)
        if not seq:
            return {"orderID": order_id, "status": "not_found"}
        return seq.pop(0) if len(seq) > 1 else seq[0]


async def _noop_sleep(*_a: Any, **_k: Any) -> None:
    return None


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
    # delayed->terminal poll uses asyncio.sleep between attempts; no-op it so the
    # poll resolves instantly in tests (interval falls back to 1.0s otherwise).
    monkeypatch.setattr(cse.asyncio, "sleep", _noop_sleep)


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


async def test_fills_cost_aggregates_and_skips_garbage() -> None:
    # alias keys + a clean row, then degenerate rows that MUST be skipped so a junk
    # payload can never corrupt the money aggregate.
    fills = [
        {"size": "10", "price": "0.40"},          # 4.0
        {"matched_amount": "5", "avg_price": "0.60"},  # 3.0 (aliases)
        {"size": "0", "price": "0.50"},           # skip: size <= 0
        {"size": "3", "price": "1.5"},            # skip: price > 1
        {"size": "2"},                            # skip: no price
        "not-a-dict",                             # skip: malformed
    ]
    size, cost = cse._fills_cost(fills)
    assert size == 15.0
    assert cost == 7.0
    assert cse._fills_cost([]) == (0.0, 0.0)
    assert cse._fills_cost(None) == (0.0, 0.0)
    # garbage in an earlier alias must NOT abort the fallback to a later valid alias
    assert cse._first_float({"size": "garbage", "amount": "10"},
                            cse._FILL_SIZE_KEYS) == 10.0
    assert cse._first_float({"size": "garbage"}, cse._FILL_SIZE_KEYS) is None


async def test_exact_fill_overrides_book_estimate(monkeypatch) -> None:
    # Books estimate yes=45.0 (ask .45) / no=50.0 (ask .50), but the broker actually
    # filled YES dearer (.46 -> 46.0). Exact-fill (get_fills) MUST book the ACTUAL
    # cost, not the stale estimate (Codex P1: stale scan-time books understate spend).
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    fy = {"orderID": "ord-y", "status": "matched"}
    fn = {"orderID": "ord-n", "status": "matched"}
    clob = FakeClob([fy, fn], fills={
        "ord-y": [{"size": "100", "price": "0.46"}],
        "ord-n": [{"size": "60", "price": "0.50"}, {"size": "40", "price": "0.50"}],
    })
    res = await _book_live(conn, clob)
    assert res["status"] == "open"
    by_side = {args[3]: args for args in conn.position_inserts}
    assert float(by_side["yes"][4]) == 46.0  # actual fill cost, not 45.0 estimate
    assert float(by_side["no"][4]) == 50.0
    assert float(by_side["yes"][5]) == 0.46   # entry_price = actual/shares


async def test_exact_fill_falls_back_to_estimate_on_incomplete_fills(monkeypatch) -> None:
    # Broker returns a SHORT fill set (60 of 100 shares) -> incomplete view -> the
    # booker keeps its pre-submit estimate rather than trusting partial data.
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    fy = {"orderID": "ord-y", "status": "matched"}
    fn = {"orderID": "ord-n", "status": "matched"}
    clob = FakeClob([fy, fn], fills={"ord-y": [{"size": "60", "price": "0.99"}]})
    res = await _book_live(conn, clob)
    assert res["status"] == "open"
    by_side = {args[3]: args for args in conn.position_inserts}
    assert float(by_side["yes"][4]) == 45.0  # estimate kept (short fill ignored)
    assert float(by_side["no"][4]) == 50.0


async def test_yes_delayed_polls_to_matched_then_both_fill(monkeypatch) -> None:
    # YES returns non-terminal `delayed`; the poll resolves it to matched, so the
    # NO leg proceeds and the pair books — instead of halting on a transient delay.
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    monkeypatch.setattr(cse.asyncio, "sleep", _noop_sleep)
    clob = FakeClob(
        [DELAYED, FILL],
        order_status={"ord-delayed": [{"orderID": "ord-delayed", "status": "matched"}]},
    )
    res = await _book_live(conn, clob)
    assert res["status"] == "open"
    assert len(clob.calls) == 2  # NO leg WAS sent after the YES delay resolved
    assert len(conn.position_inserts) == 2


async def test_no_delayed_polls_to_killed_then_unwinds(monkeypatch) -> None:
    # NO returns `delayed`; the poll resolves it to unmatched (killed) -> YES is
    # naked -> auto-unwind (the SELL then fills) -> flat.
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    monkeypatch.setattr(cse.asyncio, "sleep", _noop_sleep)
    clob = FakeClob(
        [FILL, DELAYED, FILL],  # yes fill, no delayed, unwind sell fill
        order_status={"ord-delayed": [{"orderID": "ord-delayed", "status": "unmatched"}]},
    )
    res = await _book_live(conn, clob)
    assert res["status"] == "unwound"
    assert len(clob.calls) == 3  # YES + NO + unwind SELL


async def test_yes_delayed_stays_ambiguous_halts(monkeypatch, halts) -> None:
    # YES stays `delayed` across the whole poll budget -> halt + reconcile, NO never
    # sent (we must not send the NO leg while the YES state is unknown).
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    monkeypatch.setattr(cse.asyncio, "sleep", _noop_sleep)
    clob = FakeClob(
        [DELAYED],
        order_status={"ord-delayed": [{"orderID": "ord-delayed", "status": "delayed"}]},
    )
    with pytest.raises(LivePostSubmitError, match="non-terminal status"):
        await _book_live(conn, clob)
    assert len(clob.calls) == 1  # NO leg never submitted
    assert halts and halts[0]["action"] == "pause"


async def test_unwind_delayed_polls_to_matched_then_flat(monkeypatch) -> None:
    # Unwind SELL returns `delayed`; the poll resolves it to matched -> flat.
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    monkeypatch.setattr(cse.asyncio, "sleep", _noop_sleep)
    clob = FakeClob(
        [FILL, KILL, DELAYED],  # yes fill, no kill -> unwind SELL delayed
        order_status={"ord-delayed": [{"orderID": "ord-delayed", "status": "matched"}]},
    )
    res = await _book_live(conn, clob)
    assert res["status"] == "unwound"
    assert conn.position_inserts == []  # flat — no naked position persisted


async def test_unwind_exact_fill_proceeds(monkeypatch) -> None:
    # NO kill -> YES naked -> unwind SELL. The bid-walk estimate is 44.0 (bid .44),
    # but the broker actually returned 44.5 -> exact-fill must credit the ACTUAL.
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    fill_y = {"orderID": "ord-y", "status": "matched"}
    sell = {"orderID": "ord-sell", "status": "matched"}
    clob = FakeClob([fill_y, KILL, sell], fills={
        "ord-y": [{"size": "100", "price": "0.45"}],      # naked cost actual 45.0
        "ord-sell": [{"size": "100", "price": "0.445"}],  # proceeds actual 44.5
    })
    res = await _book_live(conn, clob)
    assert res["status"] == "unwound"
    # realised = proceeds(44.5) - naked_cost(45.0) = -0.5
    assert float(res["realised_usdc"]) == -0.5
    credits = [float(a[2]) for a in conn.ledger_inserts if float(a[2]) > 0]
    assert credits == [44.5]  # actual weighted proceeds, not the 44.0 estimate
    # both legs persisted as the held-to-settlement strategy
    assert all(args[6] == cse.COMPLETE_SET_STRATEGY for args in conn.position_inserts)


async def test_persisted_cost_recomputed_from_submit_time_book(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, FILL])
    # quote implies YES avg 0.45 ($45/100sh) but the book drifted up to 0.46 ask.
    # The persisted size_usdc + entry price must reflect the SUBMIT-TIME fill cost
    # ($46), not the stale quote ($45). NO drifts down to 0.48 so the combined cost
    # ($94) stays within the gate-approved $95 budget and the set still books.
    await _book_live(
        conn, clob,
        quote=_quote(shares=100.0, yes_cost=45.0, no_cost=50.0),
        yes_book=_book(ask=0.46, bid=0.45),
        no_book=_book(ask=0.48, bid=0.47),
    )
    by_side = {args[3]: args for args in conn.position_inserts}
    assert float(by_side["yes"][4]) == 46.0  # size_usdc = recomputed fill cost
    assert by_side["yes"][5] == 0.46  # entry price = recomputed cost / shares
    assert float(by_side["no"][4]) == 48.0  # NO recomputed too


async def test_submit_cost_over_approved_budget_rejects(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([])
    # quote approved at $95; books drift up so the recomputed cost is $96 (> budget).
    # Must reject PRE-SUBMIT (no overspend of the gate-approved risk) — no orders.
    with pytest.raises(LivePreSubmitError, match="exceeds gate-approved budget"):
        await _book_live(
            conn, clob,
            quote=_quote(shares=100.0, yes_cost=45.0, no_cost=50.0),
            yes_book=_book(ask=0.46, bid=0.45),
            no_book=_book(ask=0.50, bid=0.49),
        )
    assert clob.calls == []
    assert conn.order_inserts == []


async def test_unwind_credits_weighted_bid_proceeds(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, KILL, FILL])  # yes fill, no kill, unwind sell fill
    # yes naked cost $45; yes bid 0.44 -> weighted proceeds $44 (NOT the bare sell
    # limit 0.43 * 100 = $43). The ledger credit must be the weighted $44.
    await _book_live(conn, clob, yes_book=_book(ask=0.45, bid=0.44))
    credits = [float(a[2]) for a in conn.ledger_inserts if float(a[2]) > 0]
    assert credits == [44.0]


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


async def test_yes_delayed_status_halts_not_clean_kill(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    # YES returns a non-terminal `delayed` status -> may still match -> must NOT be
    # read as a clean no_fill kill; halt + raise, NO leg never sent.
    clob = FakeClob([DELAYED])
    with pytest.raises(LivePostSubmitError):
        await _book_live(conn, clob)
    assert len(clob.calls) == 1  # NO leg not submitted
    assert conn.position_inserts == []
    assert halts and halts[0]["action"] == "pause"


async def test_no_delayed_status_after_yes_fill_tracks_yes_and_halts(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, DELAYED])  # YES filled, NO non-terminal
    with pytest.raises(LivePostSubmitError):
        await _book_live(conn, clob)
    assert len(clob.calls) == 2  # no auto-unwind (NO may still match)
    # confirmed YES persisted + tracked, halt fired
    assert len(conn.position_inserts) == 1
    assert conn.position_inserts[0][6] == cse.COMPLETE_SET_NAKED_STRATEGY
    assert halts and halts[0]["action"] == "pause"


async def test_unwind_delayed_status_halts_no_persist(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, KILL, DELAYED])  # unwind SELL non-terminal
    with pytest.raises(LivePostSubmitError):
        await _book_live(conn, clob)
    assert len(clob.calls) == 3
    assert conn.position_inserts == []  # no guessed naked/flat persist
    assert halts and halts[0]["action"] == "pause"


async def test_unwind_submit_ambiguous_halts_raises_no_persist(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    # unwind SELL post_order raises a transport-class error AFTER POST /order ->
    # ambiguous: account may already be flat. Must NOT auto-persist a re-sellable
    # position (would over-sell); halt + LivePostSubmitError for reconciliation.
    clob = FakeClob([FILL, KILL, RuntimeError("timeout after POST /order")])
    with pytest.raises(LivePostSubmitError):
        await _book_live(conn, clob)
    assert len(clob.calls) == 3  # unwind SELL was attempted
    assert conn.position_inserts == []  # NO guessed naked/flat position persisted
    assert halts and halts[0]["action"] == "pause"


async def test_unwind_presubmit_clobauth_persists_naked(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    # ClobAuthError = signing failed before the wire -> SELL never sent -> the leg
    # is DEFINITELY still naked -> persist (force-exitable) + halt.
    clob = FakeClob([FILL, KILL, ClobAuthError("signing failed")])
    res = await _book_live(conn, clob)
    assert res["status"] == "naked_halt" and res["persisted"] is True
    assert len(conn.position_inserts) == 1
    assert conn.position_inserts[0][6] == cse.COMPLETE_SET_NAKED_STRATEGY
    assert halts and halts[0]["action"] == "pause"


async def test_unwind_breaker_open_persists_naked_not_ambiguous(monkeypatch, halts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    # Breaker OPEN -> the unwind SELL is rejected with NO broker call -> definitely
    # still naked. Must persist + halt (like the auth case), NOT be mis-read as an
    # ambiguous post-submit (which would leave the YES exposure untracked).
    clob = FakeClob([FILL, KILL, ClobCircuitOpenError("breaker open")])
    res = await _book_live(conn, clob)
    assert res["status"] == "naked_halt" and res["persisted"] is True
    assert len(conn.position_inserts) == 1
    assert conn.position_inserts[0][6] == cse.COMPLETE_SET_NAKED_STRATEGY
    assert halts and halts[0]["action"] == "pause"


async def test_yes_breaker_open_clean_abort_no_exposure(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    # Breaker OPEN on the YES leg -> never sent -> clean pre-submit abort, NO leg
    # never submitted, zero exposure.
    clob = FakeClob([ClobCircuitOpenError("breaker open")])
    with pytest.raises(LivePreSubmitError):
        await _book_live(conn, clob)
    assert len(clob.calls) == 1
    assert conn.position_inserts == []


async def test_naked_persist_failure_escalates_not_swallowed(monkeypatch, halts, alerts) -> None:
    conn = FakeConn(fail_position_insert=True)
    _use_conn(monkeypatch, conn)
    clob = FakeClob([FILL, KILL, KILL])  # unwind FOK killed -> persist naked -> DB fails
    res = await _book_live(conn, clob)
    # persist failed -> status reflects it, persisted False, NOT a clean naked_halt
    assert res["status"] == "naked_halt_persist_failed"
    assert res["persisted"] is False
    assert conn.position_inserts == []  # nothing actually persisted
    # still halts + pages, and the alert says the exposure is UNTRACKED
    assert halts and halts[0]["action"] == "pause"
    assert alerts and "PERSIST FAILED" in alerts[-1]


async def test_halt_killswitch_failure_raises_hard_not_swallowed(monkeypatch, alerts) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)

    async def _failing_set_active(**_kwargs: Any) -> dict:
        raise RuntimeError("kill switch DB write failed")

    monkeypatch.setattr(cse.kill_switch, "set_active", _failing_set_active)
    # NO kill -> unwind FOK kill -> naked-halt path tries to engage the kill switch.
    # The activation fails -> must NOT return a clean naked_halt; raise hard so the
    # caller never believes trading is halted when it is not.
    clob = FakeClob([FILL, KILL, KILL])
    with pytest.raises(LivePostSubmitError, match="kill switch activation FAILED"):
        await _book_live(conn, clob)
    # operator was paged with the urgent did-not-engage alert
    assert alerts and "HALT DID NOT ENGAGE" in alerts[-1]


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
    # the CONFIRMED YES fill is persisted + tracked (force-exitable), not invisible
    assert len(conn.position_inserts) == 1
    assert conn.position_inserts[0][3] == "yes"
    assert conn.position_inserts[0][6] == cse.COMPLETE_SET_NAKED_STRATEGY
    assert len(conn.ledger_inserts) == 1  # YES cost debited


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
