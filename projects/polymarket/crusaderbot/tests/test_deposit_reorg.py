"""Deposit confirmation-depth + reorg guard (WARP-42, audit finding H6).

A USDC transfer is recorded ``pending`` on first sighting and only credits the
ledger once it is ``DEPOSIT_CONFIRMATION_DEPTH`` blocks deep (``confirmed``). A
log re-arriving with ``removed=true`` un-credits a confirmed deposit and marks
it ``reverted``. These tests drive the three state-machine helpers directly
against an in-memory ``deposits`` store, with ledger + audit mocked so we can
assert exactly when (and how often) funds move.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot import scheduler


# ---------------- fake asyncpg pool/conn backed by an in-memory store --------

class _Store:
    def __init__(self) -> None:
        self.deposits: list[dict] = []
        self.tg_by_user: dict = {}

    def find(self, tx_hash: str, log_index: int) -> dict | None:
        for d in self.deposits:
            if d["tx_hash"] == tx_hash and d["log_index"] == log_index:
                return d
        return None


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _Conn:
    def __init__(self, store: _Store) -> None:
        self.store = store

    def transaction(self):
        return _Txn()

    async def fetch(self, sql: str, *args):
        if "status='pending'" in sql and ">= $2" in sql:
            head, depth = args
            return [
                d for d in self.store.deposits
                if d["status"] == "pending"
                and d["block_number"] is not None
                and (head - d["block_number"]) >= depth
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql: str, *args):
        if "INSERT INTO deposits" in sql:
            user_id, tx_hash, log_index, amount, block_number = args
            row = self.store.find(tx_hash, log_index)
            if row is None:
                row = {
                    "id": uuid.uuid4(), "user_id": user_id, "tx_hash": tx_hash,
                    "log_index": log_index, "amount_usdc": amount,
                    "block_number": block_number, "status": "pending",
                    "confirmed_at_block": None,
                }
                self.store.deposits.append(row)
                return {"id": row["id"]}
            if row["status"] == "reverted":  # re-mined after reorg revert
                row["status"] = "pending"
                row["confirmed_at_block"] = None
                return {"id": row["id"]}
            return None  # already pending/confirmed — no-op
        if "status='confirmed'" in sql and "RETURNING id" in sql:
            dep_id, head = args
            for d in self.store.deposits:
                if d["id"] == dep_id and d["status"] == "pending":
                    d["status"] = "confirmed"
                    d["confirmed_at_block"] = head
                    return {"id": d["id"]}
            return None
        if "FOR UPDATE" in sql:
            tx_hash, log_index = args
            d = self.store.find(tx_hash, log_index)
            if d is None:
                return None
            return {"id": d["id"], "user_id": d["user_id"],
                    "amount_usdc": d["amount_usdc"], "status": d["status"]}
        if "telegram_user_id" in sql:
            (user_id,) = args
            return {"telegram_user_id": self.store.tg_by_user.get(user_id, 999)}
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql: str, *args):
        if "status='reverted'" in sql:
            (dep_id,) = args
            for d in self.store.deposits:
                if d["id"] == dep_id:
                    d["status"] = "reverted"
            return
        raise AssertionError(f"unexpected execute: {sql}")


class _Acq:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        return None


class _Pool:
    def __init__(self, store: _Store) -> None:
        self._conn = _Conn(store)

    def acquire(self):
        return _Acq(self._conn)


def _harness(store: _Store):
    """Patch get_pool + ledger + audit. Returns (credit_mock, debit_mock,
    audit_mock) context manager."""
    credit = AsyncMock()
    debit = AsyncMock()
    audit_write = AsyncMock()
    ctx = patch.multiple(
        scheduler,
        get_pool=lambda: _Pool(store),
    )
    return credit, debit, audit_write, ctx


def _run(coro):
    return asyncio.run(coro)


def _transfer(block: int, removed: bool = False) -> dict:
    return {
        "tx_hash": "0xabc", "log_index": 0, "amount": 100.0,
        "block_number": block, "to": "0xWALLET", "removed": removed,
    }


# ---------------- Test 1: not credited until N+32 reached --------------------

def test_pending_not_credited_until_confirmation_depth():
    store = _Store()
    user_id = uuid.uuid4()
    credit, debit, audit_write, ctx = _harness(store)
    with ctx, patch.object(scheduler.ledger, "credit_in_conn", credit), \
         patch.object(scheduler.ledger, "debit_in_conn", debit), \
         patch.object(scheduler.audit, "write", audit_write):
        _run(scheduler._record_pending_deposit(user_id, _transfer(block=100)))
        assert store.deposits[0]["status"] == "pending"
        credit.assert_not_awaited()

        # 10 blocks deep — still pending, no credit
        _run(scheduler._confirm_ready_deposits(head=110, depth=32))
        assert store.deposits[0]["status"] == "pending"
        credit.assert_not_awaited()

        # 32 blocks deep — confirmed + credited exactly once
        notify = _run(scheduler._confirm_ready_deposits(head=132, depth=32))
        assert store.deposits[0]["status"] == "confirmed"
        credit.assert_awaited_once()
        assert notify and notify[0][1] == Decimal("100.0")


# ---------------- Test 2: confirmed then removed=true → debited back ----------

def test_confirmed_then_reorg_removed_uncredits():
    store = _Store()
    user_id = uuid.uuid4()
    store.deposits.append({
        "id": uuid.uuid4(), "user_id": user_id, "tx_hash": "0xabc",
        "log_index": 0, "amount_usdc": Decimal("100.0"), "block_number": 100,
        "status": "confirmed", "confirmed_at_block": 132,
    })
    credit, debit, audit_write, ctx = _harness(store)
    with ctx, patch.object(scheduler.ledger, "credit_in_conn", credit), \
         patch.object(scheduler.ledger, "debit_in_conn", debit), \
         patch.object(scheduler.audit, "write", audit_write):
        _run(scheduler._revert_deposit(_transfer(block=100, removed=True)))

    assert store.deposits[0]["status"] == "reverted"
    debit.assert_awaited_once()
    assert debit.await_args.args[2] == Decimal("100.0")  # amount un-credited
    audit_write.assert_awaited_once()
    kw = audit_write.await_args.kwargs
    assert kw["action"] == "deposit_credit_reverted"
    assert kw["payload"]["uncredited"] is True


# ---------------- Test 3: pending then removed → reverted, no ledger move -----

def test_pending_then_removed_reverts_without_ledger_movement():
    store = _Store()
    user_id = uuid.uuid4()
    store.deposits.append({
        "id": uuid.uuid4(), "user_id": user_id, "tx_hash": "0xabc",
        "log_index": 0, "amount_usdc": Decimal("100.0"), "block_number": 100,
        "status": "pending", "confirmed_at_block": None,
    })
    credit, debit, audit_write, ctx = _harness(store)
    with ctx, patch.object(scheduler.ledger, "credit_in_conn", credit), \
         patch.object(scheduler.ledger, "debit_in_conn", debit), \
         patch.object(scheduler.audit, "write", audit_write):
        _run(scheduler._revert_deposit(_transfer(block=100, removed=True)))

    assert store.deposits[0]["status"] == "reverted"
    debit.assert_not_awaited()
    credit.assert_not_awaited()
    kw = audit_write.await_args.kwargs
    assert kw["action"] == "deposit_credit_reverted"
    assert kw["payload"]["uncredited"] is False


# ---------------- Test 4: idempotent — credit happens at most once ------------

def test_reappearance_credits_at_most_once():
    store = _Store()
    user_id = uuid.uuid4()
    credit, debit, audit_write, ctx = _harness(store)
    with ctx, patch.object(scheduler.ledger, "credit_in_conn", credit), \
         patch.object(scheduler.ledger, "debit_in_conn", debit), \
         patch.object(scheduler.audit, "write", audit_write):
        # same (tx_hash, log_index) seen twice in overlapping scans
        _run(scheduler._record_pending_deposit(user_id, _transfer(block=100)))
        _run(scheduler._record_pending_deposit(user_id, _transfer(block=100)))
        assert len(store.deposits) == 1  # deduped on (tx_hash, log_index)

        # confirm pass run twice — credit must fire only once
        _run(scheduler._confirm_ready_deposits(head=140, depth=32))
        _run(scheduler._confirm_ready_deposits(head=140, depth=32))
        credit.assert_awaited_once()
        assert store.deposits[0]["status"] == "confirmed"
