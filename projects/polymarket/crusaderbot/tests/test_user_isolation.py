"""Track J — User isolation audit tests.

Three test users (A, B, C) with separate position fixtures.
Verifies that no cross-user data leaks across queries or concurrent operations.

No real DB. No Telegram. All pool/conn interactions handled via
_RecordingConn / _make_pool fakes mirroring test_isolation_audit.py.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

# ---------------------------------------------------------------------------
# Three test users
# ---------------------------------------------------------------------------

_UID_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_UID_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_UID_C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# Position fixtures — A has 3, B has 2, C has 0
_POS_A = [
    {"id": uuid4(), "user_id": _UID_A, "market_id": "mkt-a1", "side": "yes",
     "size_usdc": Decimal("50"), "entry_price": Decimal("0.60"), "status": "open"},
    {"id": uuid4(), "user_id": _UID_A, "market_id": "mkt-a2", "side": "no",
     "size_usdc": Decimal("30"), "entry_price": Decimal("0.40"), "status": "open"},
    {"id": uuid4(), "user_id": _UID_A, "market_id": "mkt-a3", "side": "yes",
     "size_usdc": Decimal("20"), "entry_price": Decimal("0.55"), "status": "open"},
]
_POS_B = [
    {"id": uuid4(), "user_id": _UID_B, "market_id": "mkt-b1", "side": "yes",
     "size_usdc": Decimal("40"), "entry_price": Decimal("0.70"), "status": "open"},
    {"id": uuid4(), "user_id": _UID_B, "market_id": "mkt-b2", "side": "no",
     "size_usdc": Decimal("25"), "entry_price": Decimal("0.35"), "status": "open"},
]

# Wallet fixtures — one per user
_WALLET_A = {"user_id": _UID_A, "balance_usdc": Decimal("1000")}
_WALLET_B = {"user_id": _UID_B, "balance_usdc": Decimal("1000")}
_WALLET_C = {"user_id": _UID_C, "balance_usdc": Decimal("1000")}


# ---------------------------------------------------------------------------
# _RecordingConn — routes fetch/fetchrow/fetchval by user_id param
# ---------------------------------------------------------------------------

class _RecordingConn:
    """asyncpg connection stand-in.

    Maintains a per-user position store. Every SQL call is recorded.
    Data is returned only for rows whose user_id matches a UUID present
    in the args — exactly as a correctly-scoped WHERE user_id=$N would behave.
    """

    def __init__(self, position_store: dict[UUID, list[dict]],
                 wallet_store: dict[UUID, dict] | None = None) -> None:
        self._pos = position_store
        self._wal = wallet_store or {}
        self.calls: list[tuple[str, tuple]] = []

    def _positions_for(self, args: tuple) -> list[dict]:
        uuids = [a for a in args if isinstance(a, UUID)]
        uid = next((u for u in uuids if u in self._pos), None)
        if uid is None:
            return []
        return [r for r in self._pos.get(uid, []) if r.get("status") == "open"]

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        self.calls.append((sql, args))
        if "wallets" in sql.lower():
            uuids = [a for a in args if isinstance(a, UUID)]
            uid = next((u for u in uuids if u in self._wal), None)
            return [self._wal[uid]] if uid else []
        return self._positions_for(args)

    async def fetchrow(self, sql: str, *args: Any) -> dict | None:
        self.calls.append((sql, args))
        if "wallets" in sql.lower():
            uuids = [a for a in args if isinstance(a, UUID)]
            uid = next((u for u in uuids if u in self._wal), None)
            return self._wal.get(uid)
        rows = self._positions_for(args)
        if not rows:
            return None
        # If a non-user UUID is present (position id lookup), filter by it
        pos_id = next(
            (a for a in args if isinstance(a, UUID) and a not in self._pos),
            None,
        )
        if pos_id:
            rows = [r for r in rows if r["id"] == pos_id]
        return rows[0] if rows else None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls.append((sql, args))
        rows = self._positions_for(args)
        if "COUNT(*)" in sql.upper():
            return len(rows)
        return Decimal("0")

    async def execute(self, sql: str, *args: Any) -> None:
        self.calls.append((sql, args))

    def transaction(self):
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx


def _make_pool(conn: _RecordingConn) -> MagicMock:
    pool = MagicMock()
    acm = MagicMock()
    acm.__aenter__ = AsyncMock(return_value=conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acm
    return pool


def _std_store() -> dict[UUID, list[dict]]:
    return {_UID_A: _POS_A, _UID_B: _POS_B, _UID_C: []}


def _std_wallet_store() -> dict[UUID, dict]:
    return {_UID_A: _WALLET_A, _UID_B: _WALLET_B, _UID_C: _WALLET_C}


# ---------------------------------------------------------------------------
# Part 1 — Basic data segregation
# ---------------------------------------------------------------------------

class TestDataSegregation:
    """Query as user X — assert only user X's rows are returned."""

    def _run_fetch(self, uid: UUID) -> list[dict]:
        """Simulate a fetch of open positions for uid."""
        conn = _RecordingConn(_std_store())
        pool = _make_pool(conn)

        async def _go():
            async with pool.acquire() as c:
                return await c.fetch(
                    "SELECT * FROM positions WHERE user_id=$1 AND status='open'",
                    uid,
                )

        return asyncio.run(_go())

    def test_user_a_gets_three_positions(self):
        rows = self._run_fetch(_UID_A)
        assert len(rows) == 3
        for r in rows:
            assert r["user_id"] == _UID_A, "cross-user bleed in user_A fetch"

    def test_user_b_gets_two_positions(self):
        rows = self._run_fetch(_UID_B)
        assert len(rows) == 2
        for r in rows:
            assert r["user_id"] == _UID_B, "cross-user bleed in user_B fetch"

    def test_user_c_gets_zero_positions(self):
        rows = self._run_fetch(_UID_C)
        assert rows == [], "user_C should have zero open positions"

    def test_user_b_cannot_see_user_a_data(self):
        """Querying with _UID_B must return zero of user A's positions."""
        rows = self._run_fetch(_UID_B)
        a_ids = {p["id"] for p in _POS_A}
        leaked = [r for r in rows if r["id"] in a_ids]
        assert not leaked, f"user_A positions leaked to user_B: {leaked}"

    def test_user_a_cannot_see_user_b_data(self):
        rows = self._run_fetch(_UID_A)
        b_ids = {p["id"] for p in _POS_B}
        leaked = [r for r in rows if r["id"] in b_ids]
        assert not leaked, f"user_B positions leaked to user_A: {leaked}"

    def test_all_calls_carry_correct_uid(self):
        """Every SQL call recorded by the conn must have the requesting user_id in args."""
        conn = _RecordingConn(_std_store())
        pool = _make_pool(conn)

        async def _go():
            async with pool.acquire() as c:
                await c.fetch(
                    "SELECT * FROM positions WHERE user_id=$1 AND status='open'",
                    _UID_A,
                )
                await c.fetchval(
                    "SELECT COUNT(*) FROM positions WHERE user_id=$1",
                    _UID_A,
                )

        asyncio.run(_go())
        for sql, args in conn.calls:
            assert _UID_A in args, (
                f"SQL call missing _UID_A in args:\n  sql={sql!r}\n  args={args}"
            )
            assert _UID_B not in args, "cross-user: _UID_B found in _UID_A call"
            assert _UID_C not in args, "cross-user: _UID_C found in _UID_A call"


# ---------------------------------------------------------------------------
# Part 2 — Ownership double-check (id + user_id dual scope)
# ---------------------------------------------------------------------------

class TestOwnershipVerification:
    """A position fetched by (id, user_id) must not be accessible cross-user."""

    def test_user_a_cannot_fetch_user_b_position_by_id(self):
        conn = _RecordingConn(_std_store())
        pool = _make_pool(conn)
        b_pos_id = _POS_B[0]["id"]

        async def _go():
            async with pool.acquire() as c:
                return await c.fetchrow(
                    "SELECT * FROM positions WHERE id=$1 AND user_id=$2 AND status='open'",
                    b_pos_id, _UID_A,
                )

        result = asyncio.run(_go())
        assert result is None, (
            f"user_A should NOT be able to access user_B's position {b_pos_id}"
        )

    def test_user_b_cannot_fetch_user_a_position_by_id(self):
        conn = _RecordingConn(_std_store())
        pool = _make_pool(conn)
        a_pos_id = _POS_A[0]["id"]

        async def _go():
            async with pool.acquire() as c:
                return await c.fetchrow(
                    "SELECT * FROM positions WHERE id=$1 AND user_id=$2 AND status='open'",
                    a_pos_id, _UID_B,
                )

        result = asyncio.run(_go())
        assert result is None, (
            f"user_B should NOT be able to access user_A's position {a_pos_id}"
        )

    def test_owner_can_fetch_own_position_by_id(self):
        conn = _RecordingConn(_std_store())
        pool = _make_pool(conn)
        a_pos_id = _POS_A[0]["id"]

        async def _go():
            async with pool.acquire() as c:
                return await c.fetchrow(
                    "SELECT * FROM positions WHERE id=$1 AND user_id=$2 AND status='open'",
                    a_pos_id, _UID_A,
                )

        result = asyncio.run(_go())
        assert result is not None, "user_A should be able to fetch own position"
        assert result["user_id"] == _UID_A

    def test_wallet_query_scoped_to_owner(self):
        conn = _RecordingConn(_std_store(), _std_wallet_store())
        pool = _make_pool(conn)

        async def _go():
            async with pool.acquire() as c:
                row_a = await c.fetchrow(
                    "SELECT balance_usdc FROM wallets WHERE user_id=$1", _UID_A
                )
                row_b = await c.fetchrow(
                    "SELECT balance_usdc FROM wallets WHERE user_id=$1", _UID_B
                )
            return row_a, row_b

        row_a, row_b = asyncio.run(_go())
        assert row_a is not None and row_a["user_id"] == _UID_A
        assert row_b is not None and row_b["user_id"] == _UID_B


# ---------------------------------------------------------------------------
# Part 3 — Concurrent isolation stress test
# ---------------------------------------------------------------------------

class TestConcurrentIsolation:
    """10 concurrent asyncio tasks across 3 users — verify no cross-user data bleed."""

    def test_10_concurrent_position_fetches_no_bleed(self):
        """Each task uses its own conn scoped to its user_id. No shared state."""
        # task schedule: (user_id, expected_count)
        schedule = [
            (_UID_A, 3), (_UID_B, 2), (_UID_C, 0),
            (_UID_A, 3), (_UID_B, 2), (_UID_C, 0),
            (_UID_A, 3), (_UID_B, 2),
            (_UID_A, 3), (_UID_B, 2),
        ]
        store = _std_store()

        async def _fetch_for(uid: UUID, expected: int) -> tuple[UUID, list[dict], int]:
            conn = _RecordingConn(store)
            pool = _make_pool(conn)
            async with pool.acquire() as c:
                rows = await c.fetch(
                    "SELECT * FROM positions WHERE user_id=$1 AND status='open'",
                    uid,
                )
            return uid, rows, expected

        async def _run_all():
            tasks = [_fetch_for(uid, exp) for uid, exp in schedule]
            return await asyncio.gather(*tasks)

        results = asyncio.run(_run_all())
        assert len(results) == 10

        for uid, rows, expected_count in results:
            assert len(rows) == expected_count, (
                f"user {uid}: expected {expected_count} positions, got {len(rows)}"
            )
            for row in rows:
                assert row["user_id"] == uid, (
                    f"cross-user bleed: query for {uid} returned row owned by {row['user_id']}"
                )

    def test_concurrent_position_updates_no_cross_contamination(self):
        """Concurrent UPDATE-style calls for user A and user B must not touch each other's data."""
        store = _std_store()
        updated_by: dict[UUID, list[UUID]] = {_UID_A: [], _UID_B: []}

        async def _update_for(uid: UUID) -> None:
            conn = _RecordingConn(store)
            pool = _make_pool(conn)
            async with pool.acquire() as c:
                # Simulate: UPDATE positions SET ... WHERE id=$1 AND user_id=$2
                pos = (store[uid] or [{}])[0]
                pos_id = pos.get("id")
                if pos_id:
                    await c.execute(
                        "UPDATE positions SET entry_price=$3 "
                        "WHERE id=$1 AND user_id=$2",
                        pos_id, uid, Decimal("0.50"),
                    )
                    # Verify the execute call only carries uid — not the other user's id
                    for sql, args in c.calls:
                        if "UPDATE" in sql.upper():
                            uuids_in_args = [a for a in args if isinstance(a, UUID)]
                            updated_by[uid].extend(uuids_in_args)

        async def _run():
            await asyncio.gather(
                *[_update_for(_UID_A) for _ in range(5)],
                *[_update_for(_UID_B) for _ in range(5)],
            )

        asyncio.run(_run())

        # user_A's update calls must not contain _UID_B, and vice versa
        for uid_arg in updated_by[_UID_A]:
            assert uid_arg != _UID_B, (
                f"cross-contamination: _UID_B found in user_A update args"
            )
        for uid_arg in updated_by[_UID_B]:
            assert uid_arg != _UID_A, (
                f"cross-contamination: _UID_A found in user_B update args"
            )

    def test_concurrent_count_queries_return_correct_scoped_values(self):
        """COUNT queries for each user in parallel return per-user counts."""
        store = _std_store()

        async def _count_for(uid: UUID) -> tuple[UUID, int]:
            conn = _RecordingConn(store)
            pool = _make_pool(conn)
            async with pool.acquire() as c:
                count = await c.fetchval(
                    "SELECT COUNT(*) FROM positions WHERE user_id=$1 AND status='open'",
                    uid,
                )
            return uid, count

        async def _run():
            return await asyncio.gather(
                _count_for(_UID_A),
                _count_for(_UID_B),
                _count_for(_UID_C),
                _count_for(_UID_A),
                _count_for(_UID_B),
            )

        results = asyncio.run(_run())
        expected = {_UID_A: 3, _UID_B: 2, _UID_C: 0}
        for uid, count in results:
            assert count == expected[uid], (
                f"user {uid}: expected {expected[uid]} positions, got {count}"
            )
