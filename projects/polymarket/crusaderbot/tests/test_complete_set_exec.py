"""Unit tests for the complete-set PAPER booking primitive (Lane 2B).

No real DB: asyncpg Pool/Connection are replaced with an in-memory fake that
captures every query so we can assert the two-leg booking transaction —
2 orders + 2 cross-linked positions + 2 ledger debits, atomically, with single
idempotency identity and no TP/SL.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import complete_set_exec as cse
from projects.polymarket.crusaderbot.domain.strategy.complete_set_arb import CompleteSetQuote

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


class FakeConn:
    """Captures every query; orders RETURN ids unless their key is in `dup_keys`."""

    def __init__(self, *, dup_keys: set[str] | None = None) -> None:
        self.dup_keys = dup_keys or set()
        self.order_inserts: list[tuple] = []
        self.position_inserts: list[tuple] = []
        self.paired_updates: list[tuple] = []
        self.ledger_inserts: list[tuple] = []
        self.wallet_updates: list[tuple] = []
        self._pos_ids: list[UUID] = []

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        if "INSERT INTO orders" in query:
            self.order_inserts.append(args)
            idem = args[5]  # idempotency_key position in the INSERT
            if idem in self.dup_keys:
                return None
            return {"id": uuid4()}
        if "INSERT INTO positions" in query:
            self.position_inserts.append(args)
            pid = uuid4()
            self._pos_ids.append(pid)
            return {"id": pid}
        return None

    async def execute(self, query: str, *args: Any) -> str:
        if "UPDATE positions SET paired_position_id" in query:
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


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    """Patch get_pool + audit so the primitive runs with no DB / no network."""
    async def _noop_audit(**_kwargs: Any) -> None:
        return None
    monkeypatch.setattr(cse.audit, "write", _noop_audit)


def _use_conn(monkeypatch, conn: FakeConn) -> None:
    monkeypatch.setattr(cse, "get_pool", lambda: FakePool(conn))


async def test_happy_path_books_two_linked_legs(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    res = await cse.book_complete_set_paper(
        user_id=uuid4(), telegram_user_id=7, quote=_quote(),
        market_question="ETH up?", idempotency_key="set:k1",
    )
    assert res["status"] == "open"
    assert res["shares"] == 100.0
    assert res["yes_position_id"] and res["no_position_id"]
    # 2 orders, 2 positions, 2 cross-link updates, 2 ledger debits + 2 wallet upd
    assert len(conn.order_inserts) == 2
    assert len(conn.position_inserts) == 2
    assert len(conn.paired_updates) == 2
    assert len(conn.ledger_inserts) == 2
    assert len(conn.wallet_updates) == 2
    # the two paired updates point each leg at the other
    a, b = conn.paired_updates
    assert a[0] == b[1] and b[0] == a[1]


async def test_idempotency_keys_are_per_leg(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    await cse.book_complete_set_paper(
        user_id=uuid4(), telegram_user_id=7, quote=_quote(),
        market_question=None, idempotency_key="set:k1",
    )
    keys = {args[5] for args in conn.order_inserts}
    assert keys == {"set:k1:yes", "set:k1:no"}


async def test_per_leg_pricing_and_no_tp_sl(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    await cse.book_complete_set_paper(
        user_id=uuid4(), telegram_user_id=7,
        quote=_quote(shares=100.0, yes_cost=45.0, no_cost=50.0),
        market_question=None, idempotency_key="k",
    )
    # position INSERT args: (user, market, order, side, size, price, strat, q, preset, meta_json)
    by_side = {args[3]: args for args in conn.position_inserts}
    assert float(by_side["yes"][4]) == 45.0 and by_side["yes"][5] == 0.45
    assert float(by_side["no"][4]) == 50.0 and by_side["no"][5] == 0.50
    # strategy_type stamped
    assert by_side["yes"][6] == cse.COMPLETE_SET_STRATEGY


async def test_metadata_snapshot_rides_both_legs(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    await cse.book_complete_set_paper(
        user_id=uuid4(), telegram_user_id=7, quote=_quote(),
        market_question=None, idempotency_key="k",
    )
    for args in conn.position_inserts:
        meta = json.loads(args[9])  # strategy_metadata json is the last arg
        assert meta["complete_set"] is True
        assert meta["condition_id"] == "c1"
        assert meta["yes_token_id"] == "ytok" and meta["no_token_id"] == "ntok"


async def test_duplicate_set_books_nothing(monkeypatch) -> None:
    conn = FakeConn(dup_keys={"k:yes", "k:no"})
    _use_conn(monkeypatch, conn)
    res = await cse.book_complete_set_paper(
        user_id=uuid4(), telegram_user_id=7, quote=_quote(),
        market_question=None, idempotency_key="k",
    )
    assert res["status"] == "duplicate"
    assert conn.position_inserts == []
    assert conn.ledger_inserts == []


async def test_partial_idempotency_raises_to_rollback(monkeypatch) -> None:
    # only the YES key already booked → a half set → must raise (txn rolls back)
    conn = FakeConn(dup_keys={"k:yes"})
    _use_conn(monkeypatch, conn)
    with pytest.raises(RuntimeError, match="partial idempotency"):
        await cse.book_complete_set_paper(
            user_id=uuid4(), telegram_user_id=7, quote=_quote(),
            market_question=None, idempotency_key="k",
        )
    assert conn.position_inserts == []


async def test_non_positive_shares_skipped(monkeypatch) -> None:
    conn = FakeConn()
    _use_conn(monkeypatch, conn)
    res = await cse.book_complete_set_paper(
        user_id=uuid4(), telegram_user_id=7,
        quote=_quote(shares=0.0, yes_cost=0.0, no_cost=0.0),
        market_question=None, idempotency_key="k",
    )
    assert res["status"] == "skipped"
    assert conn.order_inserts == []
