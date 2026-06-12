"""End-to-end deposit pipeline simulation (WARP-94).

Drives the full ``scheduler.watch_deposits()`` orchestration against an
in-memory ``deposits`` / ``chain_cursor`` / ``wrong_token_deposits`` store with
the chain reader (``polygon.scan_from_cursor`` / ``latest_block``), ledger,
audit, and telegram notifications mocked. Asserts the complete DB state change
for the two paths the audit hardened:

  1. A USDC.e Transfer to a known deposit address → ``deposits`` row created,
     credited to the ledger once it is confirmation-depth deep, balance moves.
  2. A native-USDC Transfer to the same address → ``wrong_token_deposits`` row
     created, user alerted, and the ledger is NEVER touched (no credit).
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot import scheduler


class _Settings:
    DEPOSIT_CONFIRMATION_DEPTH = 32
    WRONG_TOKEN_ALERTS_ENABLED = True
    USDC_NATIVE_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    DEPOSIT_SCAN_LOOKBACK_BLOCKS = 50_000


# ---------------- in-memory store + fake asyncpg pool ------------------------

class _Store:
    def __init__(self) -> None:
        self.deposits: list[dict] = []
        self.wrong: list[dict] = []
        self.cursors: dict[str, int] = {}
        self.tg_by_user: dict = {}

    def find_deposit(self, tx_hash: str, log_index: int) -> dict | None:
        for d in self.deposits:
            if d["tx_hash"] == tx_hash and d["log_index"] == log_index:
                return d
        return None

    def find_wrong(self, tx_hash: str, log_index: int) -> dict | None:
        for w in self.wrong:
            if w["tx_hash"] == tx_hash and w["log_index"] == log_index:
                return w
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
        # Step 3 (#per-user-watcher) widened the SELECT to also pull
        # polymarket_deposit_wallet. Match the column-prefix so this
        # fixture doesn't break on every future column add to the watcher.
        if (
            "SELECT user_id, deposit_address, safe_address" in sql
            and "FROM wallets" in sql
        ):
            return self.store.wallet_rows
        if "status='pending'" in sql and ">= $2" in sql:
            head, depth = args
            return [
                d for d in self.store.deposits
                if d["status"] == "pending"
                and d["block_number"] is not None
                and (head - d["block_number"]) >= depth
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchval(self, sql: str, *args):
        if "block_number FROM chain_cursor" in sql:
            (name,) = args
            return self.store.cursors.get(name, 0)
        raise AssertionError(f"unexpected fetchval: {sql}")

    async def fetchrow(self, sql: str, *args):
        if "INSERT INTO deposits" in sql:
            user_id, tx_hash, log_index, amount, block_number = args
            row = self.store.find_deposit(tx_hash, log_index)
            if row is None:
                row = {
                    "id": uuid.uuid4(), "user_id": user_id, "tx_hash": tx_hash,
                    "log_index": log_index, "amount_usdc": amount,
                    "block_number": block_number, "status": "pending",
                    "confirmed_at_block": None, "swept": False,
                    "lifecycle_state": "confirming",
                }
                self.store.deposits.append(row)
                return {"id": row["id"]}
            return None
        if "INSERT INTO wrong_token_deposits" in sql:
            user_id, token, tx_hash, log_index, amount, block_number = args
            if self.store.find_wrong(tx_hash, log_index) is not None:
                return None  # ON CONFLICT DO NOTHING
            row = {
                "id": len(self.store.wrong) + 1, "user_id": user_id,
                "token_address": token, "tx_hash": tx_hash,
                "log_index": log_index, "amount": amount,
                "block_number": block_number,
            }
            self.store.wrong.append(row)
            return {"id": row["id"]}
        if "status='confirmed'" in sql and "RETURNING id" in sql:
            dep_id, head = args
            for d in self.store.deposits:
                if d["id"] == dep_id and d["status"] == "pending":
                    d["status"] = "confirmed"
                    d["confirmed_at_block"] = head
                    d["lifecycle_state"] = "available"
                    return {"id": d["id"]}
            return None
        if "telegram_user_id" in sql:
            (user_id,) = args
            return {"telegram_user_id": self.store.tg_by_user.get(user_id, 999)}
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql: str, *args):
        if "INSERT INTO chain_cursor" in sql:
            name, block_number = args
            self.store.cursors[name] = block_number
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


def _run(coro):
    return asyncio.run(coro)


WALLET = "0x5827edEf918dc6bf38D5b7D7bbf0A53dF5e8F808"


def _store_with_wallet(user_id) -> _Store:
    store = _Store()
    store.wallet_rows = [
        {"user_id": user_id, "deposit_address": WALLET, "safe_address": None},
    ]
    store.tg_by_user[user_id] = 12345
    return store


# ---------------- Test 1: full USDC.e deposit pipeline credits once ----------

def test_e2e_usdce_deposit_records_confirms_credits():
    store = _store_with_wallet(uuid.uuid4())
    credit = AsyncMock()
    depth = _Settings.DEPOSIT_CONFIRMATION_DEPTH

    usdce_transfer = {
        "tx_hash": "0xdeposit", "log_index": 0, "amount": 25.0,
        "block_number": 100, "to": WALLET, "removed": False,
    }

    async def fake_scan(addresses, cursor, token_address=None, lookback=2000,
                        max_rpc=60):
        # USDC.e (default token) returns the deposit; native returns nothing.
        if token_address is None:
            return [usdce_transfer], 100
        return [], 100

    with patch.object(scheduler, "get_pool", lambda: _Pool(store)), \
         patch.object(scheduler, "get_settings", return_value=_Settings()), \
         patch.object(scheduler.polygon, "latest_block", AsyncMock(return_value=100)), \
         patch.object(scheduler.polygon, "scan_from_cursor", side_effect=fake_scan), \
         patch.object(scheduler.ledger, "credit_in_conn", credit), \
         patch.object(scheduler.ledger, "debit_in_conn", AsyncMock()), \
         patch.object(scheduler.audit, "write", AsyncMock()), \
         patch.object(scheduler.notifications, "send", AsyncMock()):
        # Tick 1: head only 100 → recorded pending, not yet credited.
        _run(scheduler.watch_deposits())
        assert len(store.deposits) == 1
        assert store.deposits[0]["status"] == "pending"
        credit.assert_not_awaited()

        # Tick 2: head now depth-deep → confirmed + credited exactly once.
        with patch.object(scheduler.polygon, "latest_block",
                          AsyncMock(return_value=100 + depth)):
            _run(scheduler.watch_deposits())
        assert store.deposits[0]["status"] == "confirmed"
        # Guards OFF: realtime sweep is DEFERRED — the row must stay
        # sweep-eligible (swept=FALSE) and truthfully 'available'.
        assert store.deposits[0]["swept"] is False
        assert store.deposits[0]["lifecycle_state"] == "available"
        credit.assert_awaited_once()
        assert credit.await_args.args[2] == Decimal("25.0")
        # No wrong-token rows from a legitimate USDC.e deposit.
        assert store.wrong == []


# ---------------- Test 2: native-USDC deposit alerts, never credits ----------

def test_e2e_native_usdc_alerts_without_crediting():
    store = _store_with_wallet(uuid.uuid4())
    credit = AsyncMock()
    notify = AsyncMock()

    native_transfer = {
        "tx_hash": "0xwrongtoken", "log_index": 0, "amount": 40.0,
        "block_number": 200, "to": WALLET, "removed": False,
    }

    async def fake_scan(addresses, cursor, token_address=None, lookback=2000,
                        max_rpc=60):
        if token_address is None:
            return [], 200  # no USDC.e deposits
        return [native_transfer], 200  # native USDC seen

    with patch.object(scheduler, "get_pool", lambda: _Pool(store)), \
         patch.object(scheduler, "get_settings", return_value=_Settings()), \
         patch.object(scheduler.polygon, "latest_block", AsyncMock(return_value=200)), \
         patch.object(scheduler.polygon, "scan_from_cursor", side_effect=fake_scan), \
         patch.object(scheduler.ledger, "credit_in_conn", credit), \
         patch.object(scheduler.ledger, "debit_in_conn", AsyncMock()), \
         patch.object(scheduler.audit, "write", AsyncMock()), \
         patch.object(scheduler.notifications, "send", notify):
        _run(scheduler.watch_deposits())

        # No deposit credited; ledger untouched.
        assert store.deposits == []
        credit.assert_not_awaited()
        # Wrong-token row recorded and the user warned exactly once.
        assert len(store.wrong) == 1
        assert store.wrong[0]["tx_hash"] == "0xwrongtoken"
        warn_calls = [c for c in notify.await_args_list
                      if "Wrong token" in c.args[1]]
        assert len(warn_calls) == 1

        # Re-run over an overlapping range → idempotent, no second alert.
        notify.reset_mock()
        _run(scheduler.watch_deposits())
        assert len(store.wrong) == 1
        warn_calls = [c for c in notify.await_args_list
                      if "Wrong token" in c.args[1]]
        assert warn_calls == []
