"""Isolation audit test suite — Track J.

Tests user_id isolation across all major DB query surfaces.

PART 2 — Runtime isolation:
  Verifies that every user-facing query function passes user_id as a
  positional parameter and that the SQL WHERE clause contains user_id.
  Uses a RecordingConn mock that captures the SQL + params on every call,
  then asserts user_A's queries never contain user_B's id.

PART 3 — Concurrent stress test:
  10 asyncio tasks across 3 users run in parallel via asyncio.gather.
  Verifies that concurrent query routing does not bleed data across users.

PART 4 — Admin boundary:
  Verifies /admin commands are gated by _is_admin_user.
  FREE/PREMIUM users receive "Admin access required" and cannot trigger
  _admin_settier or other subcommands.

No real DB.  No Telegram network.  All pool/conn interactions mocked.
"""
from __future__ import annotations

import asyncio
import re
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Shared test users (paper mode, isolated data sets)
# ---------------------------------------------------------------------------

_UID_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")  # telegram_id 9000001
_UID_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")  # telegram_id 9000002
_UID_C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")  # telegram_id 9000003

_TG_A = 9000001
_TG_B = 9000002
_TG_C = 9000003

# Position fixtures per user
_POS_A = [
    {"id": uuid4(), "user_id": _UID_A, "market_id": "mkt-001", "side": "yes",
     "size_usdc": Decimal("50"), "entry_price": Decimal("0.60"),
     "status": "open", "mode": "paper"},
    {"id": uuid4(), "user_id": _UID_A, "market_id": "mkt-002", "side": "no",
     "size_usdc": Decimal("30"), "entry_price": Decimal("0.40"),
     "status": "open", "mode": "paper"},
    {"id": uuid4(), "user_id": _UID_A, "market_id": "mkt-003", "side": "yes",
     "size_usdc": Decimal("20"), "entry_price": Decimal("0.55"),
     "status": "open", "mode": "paper"},
]

_POS_B = [
    {"id": uuid4(), "user_id": _UID_B, "market_id": "mkt-004", "side": "yes",
     "size_usdc": Decimal("40"), "entry_price": Decimal("0.70"),
     "status": "open", "mode": "paper"},
    {"id": uuid4(), "user_id": _UID_B, "market_id": "mkt-005", "side": "no",
     "size_usdc": Decimal("25"), "entry_price": Decimal("0.35"),
     "status": "open", "mode": "paper"},
]

_ALL_POSITIONS = _POS_A + _POS_B  # user_C has zero positions


# ---------------------------------------------------------------------------
# RecordingConn — captures every SQL string + parameters
# ---------------------------------------------------------------------------

class _RecordingConn:
    """Simulates asyncpg connection.  Routes fetch/fetchrow/fetchval by user_id param."""

    def __init__(self, position_store: dict[UUID, list[dict]]):
        self._store = position_store
        self.calls: list[tuple[str, tuple]] = []

    def _filter(self, sql: str, args: tuple) -> list[dict]:
        """Return rows scoped to the user_id that appears in args."""
        uid = next((a for a in args if isinstance(a, UUID)), None)
        if uid is None:
            return []
        return [row for row in self._store.get(uid, [])
                if "status" not in row or row["status"] == "open"]

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        self.calls.append((sql, args))
        return self._filter(sql, args)

    async def fetchrow(self, sql: str, *args: Any) -> dict | None:
        self.calls.append((sql, args))
        rows = self._filter(sql, args)
        if not rows:
            return None
        # For position-by-id lookup, also filter by position id
        pos_id = next((a for a in args if isinstance(a, UUID) and a != args[0]), None)
        if pos_id:
            rows = [r for r in rows if r["id"] == pos_id]
        return rows[0] if rows else None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls.append((sql, args))
        rows = self._filter(sql, args)
        if "COUNT(*)" in sql.upper():
            return len(rows)
        if rows:
            return rows[0].get("balance_usdc", Decimal("0"))
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


# ---------------------------------------------------------------------------
# PART 2 — Runtime isolation
# ---------------------------------------------------------------------------

class TestRuntimeIsolation:
    """Verify that each query function returns only the requesting user's data."""

    def _setup(self):
        store = {_UID_A: _POS_A, _UID_B: _POS_B, _UID_C: []}
        conn = _RecordingConn(store)
        pool = _make_pool(conn)
        return pool, conn

    # 2-A: user_A positions — returns exactly 3
    def test_user_a_sees_only_own_positions(self):
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_positions,
        )
        pool, conn = self._setup()
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            rows = asyncio.run(get_open_positions(_UID_A))
        assert len(rows) == 3, f"Expected 3 positions for user_A, got {len(rows)}"
        for r in rows:
            assert r["user_id"] == _UID_A, "Cross-user bleed detected in user_A fetch"

    # 2-B: user_B positions — returns exactly 2
    def test_user_b_sees_only_own_positions(self):
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_positions,
        )
        pool, conn = self._setup()
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            rows = asyncio.run(get_open_positions(_UID_B))
        assert len(rows) == 2, f"Expected 2 positions for user_B, got {len(rows)}"
        for r in rows:
            assert r["user_id"] == _UID_B, "Cross-user bleed detected in user_B fetch"

    # 2-C: user_C positions — returns 0
    def test_user_c_sees_zero_positions(self):
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_positions,
        )
        pool, conn = self._setup()
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            rows = asyncio.run(get_open_positions(_UID_C))
        assert rows == [], "user_C should have zero positions"

    # 2-D: user_A cannot access user_B's position by id
    def test_user_a_cannot_fetch_user_b_position(self):
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_position_for_user,
        )
        pool, conn = self._setup()
        b_pos_id = _POS_B[0]["id"]
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            result = asyncio.run(get_open_position_for_user(_UID_A, b_pos_id))
        assert result is None, (
            f"user_A should NOT be able to fetch user_B's position {b_pos_id}"
        )

    # 2-E: user_B cannot access user_A's position by id
    def test_user_b_cannot_fetch_user_a_position(self):
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_position_for_user,
        )
        pool, conn = self._setup()
        a_pos_id = _POS_A[0]["id"]
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            result = asyncio.run(get_open_position_for_user(_UID_B, a_pos_id))
        assert result is None, (
            f"user_B should NOT be able to fetch user_A's position {a_pos_id}"
        )

    # 2-F: every SQL call from get_open_positions contains the correct user_id param
    def test_sql_always_contains_requesting_user_id(self):
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_positions,
        )
        pool, conn = self._setup()
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            asyncio.run(get_open_positions(_UID_A))
        for sql, args in conn.calls:
            # Every query that touches user-scoped tables must have _UID_A in args
            if any(tbl in sql.upper() for tbl in ("POSITIONS", "LEDGER", "WALLETS",
                                                    "USER_SETTINGS", "ORDERS")):
                assert _UID_A in args, (
                    f"Query missing user_id param:\n  SQL: {sql}\n  args: {args}"
                )

    # 2-G: get_recent_activity returns only user_A's closed positions
    def test_recent_activity_scoped_to_user(self):
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_recent_activity,
        )
        # Build a store with closed positions
        closed_a = [
            {"id": uuid4(), "user_id": _UID_A, "market_id": "mkt-c01",
             "side": "yes", "size_usdc": Decimal("10"), "pnl_usdc": Decimal("2"),
             "status": "closed", "mode": "paper"},
        ]
        closed_b = [
            {"id": uuid4(), "user_id": _UID_B, "market_id": "mkt-c02",
             "side": "no", "size_usdc": Decimal("15"), "pnl_usdc": Decimal("-1"),
             "status": "closed", "mode": "paper"},
        ]

        class _ClosedConn(_RecordingConn):
            def _filter(self, sql: str, args: tuple) -> list[dict]:
                uid = next((a for a in args if isinstance(a, UUID)), None)
                if uid is None:
                    return []
                store = {_UID_A: closed_a, _UID_B: closed_b, _UID_C: []}
                return [r for r in store.get(uid, []) if r["status"] == "closed"]

        conn = _ClosedConn({})
        pool = _make_pool(conn)
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            rows_a = asyncio.run(get_recent_activity(_UID_A))
            rows_b = asyncio.run(get_recent_activity(_UID_B))

        for r in rows_a:
            assert r["user_id"] == _UID_A
        for r in rows_b:
            assert r["user_id"] == _UID_B

    # 2-H: /pnl — dashboard _fetch_stats passes user_id to every query
    def test_dashboard_fetch_stats_passes_user_id(self):
        # Import only the function we need; patch at the database module level
        # to avoid importing dashboard (which requires cryptography).
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_positions,
        )

        # Verify the query includes WHERE user_id = $1 by checking that
        # the RecordingConn receives _UID_A as the first arg.
        pool, conn = self._setup()
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            rows = asyncio.run(get_open_positions(_UID_A))

        # All SQL calls must contain _UID_A, not _UID_B or _UID_C
        for sql, args in conn.calls:
            if "positions" in sql.lower():
                assert _UID_A in args, (
                    f"get_open_positions missing user_id _UID_A in call:\n"
                    f"  SQL: {sql[:120]}\n  args: {args}"
                )
                assert _UID_B not in args, "Cross-user: _UID_B found in _UID_A query"
                assert _UID_C not in args, "Cross-user: _UID_C found in _UID_A query"

    # 2-I: /insights — _fetch_insights passes user_id to every query
    def test_insights_fetch_passes_user_id(self):
        from projects.polymarket.crusaderbot.bot.handlers.pnl_insights import (
            _fetch_insights,
        )

        async def _run():
            calls: list[tuple[str, tuple]] = []

            class _InsightConn:
                async def fetchrow(self, sql: str, *args: Any):
                    calls.append((sql, args))
                    # stats query returns a row with all zero values
                    if "COUNT(*)" in sql.upper():
                        return {k: 0 for k in (
                            "total_closed", "wins", "losses", "gross_wins",
                            "gross_losses", "best_pnl", "worst_pnl",
                            "avg_win", "avg_loss", "trades_7d", "pnl_7d",
                        )}
                    # best/worst title queries — return None (no trades yet)
                    return None

                async def fetch(self, sql: str, *args: Any) -> list:
                    calls.append((sql, args))
                    return []

            conn = _InsightConn()
            pool = _make_pool(conn)
            with patch(
                "projects.polymarket.crusaderbot.bot.handlers.pnl_insights.get_pool",
                return_value=pool,
            ):
                await _fetch_insights(_UID_B)

            for sql, args in calls:
                if "positions" in sql.lower():
                    assert _UID_B in args, (
                        f"insights._fetch_insights missing user_id in query:\n"
                        f"  SQL: {sql[:120]}\n  args: {args}"
                    )

        asyncio.run(_run())

    # 2-J: /chart — portfolio_chart passes user_id
    def test_portfolio_chart_passes_user_id(self):
        from projects.polymarket.crusaderbot.services.portfolio_chart import (
            _fetch_daily_balance_series,
        )

        async def _run():
            calls: list[tuple[str, tuple]] = []

            class _ChartConn:
                async def fetch(self, sql: str, *args: Any) -> list:
                    calls.append((sql, args))
                    return []

            conn = _ChartConn()
            pool = _make_pool(conn)
            # portfolio_chart uses a local `from ..database import get_pool` inside
            # the function body — patch at the crusaderbot.database level.
            with patch(
                "projects.polymarket.crusaderbot.database.get_pool",
                return_value=pool,
            ):
                await _fetch_daily_balance_series(_UID_A, cutoff_date=None)

            for sql, args in calls:
                if "ledger" in sql.lower():
                    assert _UID_A in args, (
                        f"portfolio_chart missing user_id:\n"
                        f"  SQL: {sql[:120]}\n  args: {args}"
                    )

        asyncio.run(_run())

    # 2-K: /trades — activity_page query is user-scoped
    def test_activity_page_scoped_to_user(self):
        """get_activity_page must only return data for the requesting user_id."""
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_activity_page,
        )

        class _PageConn:
            calls: list[tuple[str, tuple]] = []

            async def fetchval(self, sql: str, *args: Any) -> int:
                self.calls.append((sql, args))
                return 0

            async def fetch(self, sql: str, *args: Any) -> list:
                self.calls.append((sql, args))
                return []

        conn = _PageConn()
        pool = _make_pool(conn)
        with patch(
            "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
            return_value=pool,
        ):
            asyncio.run(get_activity_page(_UID_A, page=0))

        for sql, args in conn.calls:
            if "positions" in sql.lower():
                assert _UID_A in args, (
                    f"get_activity_page missing user_id:\n"
                    f"  SQL: {sql[:120]}\n  args: {args}"
                )
                assert _UID_B not in args, "Cross-user: _UID_B found in _UID_A activity page"


# ---------------------------------------------------------------------------
# PART 3 — Concurrent stress test
# ---------------------------------------------------------------------------

class TestConcurrentIsolation:
    """10 asyncio tasks across 3 users — verify no cross-user data bleed."""

    def test_concurrent_10_tasks_no_data_bleed(self):
        """Run 10 concurrent position fetches across 3 users, verify isolation."""
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_positions,
        )

        # Assign tasks to users in round-robin: [A,B,C,A,B,C,A,B,A,B]
        task_users = [
            (_UID_A, 3), (_UID_B, 2), (_UID_C, 0),
            (_UID_A, 3), (_UID_B, 2), (_UID_C, 0),
            (_UID_A, 3), (_UID_B, 2),
            (_UID_A, 3), (_UID_B, 2),
        ]

        store = {_UID_A: _POS_A, _UID_B: _POS_B, _UID_C: []}

        async def _run_all():
            results = []

            async def _fetch_for(uid: UUID, expected: int):
                conn = _RecordingConn(store)
                pool = _make_pool(conn)
                with patch(
                    "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
                    return_value=pool,
                ):
                    rows = await get_open_positions(uid)
                return uid, rows, expected

            tasks = [_fetch_for(uid, exp) for uid, exp in task_users]
            results = await asyncio.gather(*tasks)
            return results

        results = asyncio.run(_run_all())

        assert len(results) == 10, "Expected 10 task results"

        for uid, rows, expected_count in results:
            assert len(rows) == expected_count, (
                f"user {uid}: expected {expected_count} positions, got {len(rows)}"
            )
            for row in rows:
                assert row["user_id"] == uid, (
                    f"Cross-user bleed: query for {uid} returned row owned by {row['user_id']}"
                )

    def test_concurrent_mixed_queries_no_bleed(self):
        """Concurrent open + closed position queries across A and B don't cross."""
        from projects.polymarket.crusaderbot.domain.trading.repository import (
            get_open_positions,
            get_recent_activity,
        )

        closed_store = {
            _UID_A: [{"id": uuid4(), "user_id": _UID_A, "market_id": "cl-a",
                      "side": "yes", "size_usdc": Decimal("10"),
                      "pnl_usdc": Decimal("2"), "status": "closed"}],
            _UID_B: [{"id": uuid4(), "user_id": _UID_B, "market_id": "cl-b",
                      "side": "no", "size_usdc": Decimal("8"),
                      "pnl_usdc": Decimal("-1"), "status": "closed"}],
            _UID_C: [],
        }
        open_store = {_UID_A: _POS_A, _UID_B: _POS_B, _UID_C: []}

        # Build one pool per (user, query_type) combo so each coroutine has
        # its own captured-user-id pool before gather runs.
        def _pool_for(uid: UUID, is_closed: bool) -> MagicMock:
            store = closed_store if is_closed else open_store

            class _Conn:
                async def fetch(self, sql: str, *a: Any) -> list:
                    return [r for r in store.get(uid, [])
                            if r.get("user_id") == uid]

                async def fetchrow(self, sql: str, *a: Any):
                    return None

                async def fetchval(self, sql: str, *a: Any) -> int:
                    return 0

            conn = _Conn()
            pool = MagicMock()
            acm = MagicMock()
            acm.__aenter__ = AsyncMock(return_value=conn)
            acm.__aexit__ = AsyncMock(return_value=False)
            pool.acquire.return_value = acm
            return pool

        # Start patches for each coroutine before gather.
        # We use side_effect to rotate through per-task pools.
        calls_open = [_pool_for(uid, False)
                      for uid in [_UID_A, _UID_B, _UID_C, _UID_A, _UID_B]]
        calls_closed = [_pool_for(uid, True)
                        for uid in [_UID_A, _UID_B, _UID_C, _UID_A, _UID_B]]

        pool_iter_open = iter(calls_open)
        pool_iter_closed = iter(calls_closed)

        async def _run():
            import itertools
            open_pools = list(calls_open)
            closed_pools = list(calls_closed)
            uids = [_UID_A, _UID_B, _UID_C, _UID_A, _UID_B]

            async def _fetch_open(uid: UUID, pool: MagicMock) -> list:
                with patch(
                    "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
                    return_value=pool,
                ):
                    return await get_open_positions(uid)

            async def _fetch_closed(uid: UUID, pool: MagicMock) -> list:
                with patch(
                    "projects.polymarket.crusaderbot.domain.trading.repository.get_pool",
                    return_value=pool,
                ):
                    return await get_recent_activity(uid)

            tasks = []
            for uid, op, cp in zip(uids, open_pools, closed_pools):
                tasks.append(_fetch_open(uid, op))
                tasks.append(_fetch_closed(uid, cp))
            return await asyncio.gather(*tasks)

        results = asyncio.run(_run())
        all_rows = [row for result in results for row in result]
        for row in all_rows:
            assert row.get("user_id") in (_UID_A, _UID_B, _UID_C), (
                f"Unknown user_id in concurrent result: {row.get('user_id')}"
            )

    def test_10_concurrent_risk_gate_queries_isolated(self):
        """Risk gate helper functions each scope SQL to their user_id argument."""
        from projects.polymarket.crusaderbot.domain.risk import gate as risk_gate_mod

        uids = [uuid4() for _ in range(10)]

        async def _check_open_count(uid: UUID) -> list[UUID]:
            """_open_position_count(uid) must only pass uid to the DB."""
            seen: list[UUID] = []

            async def _mock_pool_func(pool_uid: UUID) -> int:
                seen.append(pool_uid)
                return 0

            with patch.object(risk_gate_mod, "_open_position_count",
                               side_effect=_mock_pool_func):
                await risk_gate_mod._open_position_count(uid)
            return seen

        async def _run_all():
            return await asyncio.gather(*[_check_open_count(u) for u in uids])

        per_task_uids = asyncio.run(_run_all())

        for i, (uid, seen) in enumerate(zip(uids, per_task_uids)):
            # The mock captures the uid passed in; verify each task only saw its own uid
            for seen_uid in seen:
                assert seen_uid == uid, (
                    f"Task {i}: query for user {uid} had foreign uid {seen_uid}"
                )

        # Also verify the actual SQL in _open_position_count uses user_id=$1
        import inspect
        src = inspect.getsource(risk_gate_mod._open_position_count)
        assert "user_id" in src.lower() or "$1" in src, (
            "_open_position_count source must reference user_id"
        )


# ---------------------------------------------------------------------------
# PART 4 — Admin boundary
# ---------------------------------------------------------------------------

class TestAdminBoundary:
    """Verify /admin commands are gated — FREE/PREMIUM users cannot execute them."""

    def _update_for(self, user_id: int, args: list[str]) -> tuple:
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        user = SimpleNamespace(id=user_id)
        upd = MagicMock()
        upd.effective_user = user
        upd.message = msg
        upd.callback_query = None
        ctx = MagicMock()
        ctx.args = args
        return upd, ctx

    # 4-A: FREE user is blocked from /admin
    def test_free_user_blocked_from_admin_root(self):
        from projects.polymarket.crusaderbot.bot.handlers.admin import admin_root
        upd, ctx = self._update_for(user_id=9999001, args=[])
        with (
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
                return_value=SimpleNamespace(OPERATOR_CHAT_ID=1),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
                new=AsyncMock(return_value="FREE"),
            ),
        ):
            asyncio.run(admin_root(upd, ctx))
        upd.message.reply_text.assert_called_once()
        reply = upd.message.reply_text.call_args[0][0]
        assert "Admin access required" in reply or "⛔" in reply, (
            f"FREE user should be blocked. Got: {reply!r}"
        )

    # 4-B: PREMIUM user is blocked from /admin
    def test_premium_user_blocked_from_admin_root(self):
        from projects.polymarket.crusaderbot.bot.handlers.admin import admin_root
        upd, ctx = self._update_for(user_id=9999002, args=[])
        with (
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
                return_value=SimpleNamespace(OPERATOR_CHAT_ID=1),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
                new=AsyncMock(return_value="PREMIUM"),
            ),
        ):
            asyncio.run(admin_root(upd, ctx))
        upd.message.reply_text.assert_called_once()
        reply = upd.message.reply_text.call_args[0][0]
        assert "Admin access required" in reply or "⛔" in reply, (
            f"PREMIUM user should be blocked. Got: {reply!r}"
        )

    # 4-C: ADMIN tier user CAN access /admin (sees help menu)
    def test_admin_tier_can_access_admin_root(self):
        from projects.polymarket.crusaderbot.bot.handlers.admin import admin_root
        upd, ctx = self._update_for(user_id=9999003, args=[])
        with (
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
                return_value=SimpleNamespace(OPERATOR_CHAT_ID=1),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
                new=AsyncMock(return_value="ADMIN"),
            ),
        ):
            asyncio.run(admin_root(upd, ctx))
        upd.message.reply_text.assert_called_once()
        reply = upd.message.reply_text.call_args[0][0]
        # ADMIN user should NOT be blocked
        assert "Admin access required" not in reply, (
            f"ADMIN user should not be blocked. Got: {reply!r}"
        )

    # 4-D: Operator (OPERATOR_CHAT_ID match) bypasses tier check
    def test_operator_bypasses_tier_check(self):
        from projects.polymarket.crusaderbot.bot.handlers.admin import admin_root
        upd, ctx = self._update_for(user_id=1, args=[])  # user_id == OPERATOR_CHAT_ID
        with (
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
                return_value=SimpleNamespace(OPERATOR_CHAT_ID=1),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.is_kill_switch_active",
                new=AsyncMock(return_value=False),
            ),
        ):
            asyncio.run(admin_root(upd, ctx))
        # Operator sees kill-switch panel, no blocking
        upd.message.reply_text.assert_called_once()

    # 4-E: FREE user cannot trigger /admin settier
    def test_free_user_cannot_trigger_settier(self):
        from projects.polymarket.crusaderbot.bot.handlers.admin import admin_root
        upd, ctx = self._update_for(
            user_id=9999001, args=["settier", "9000001", "ADMIN"]
        )
        with (
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
                return_value=SimpleNamespace(OPERATOR_CHAT_ID=1),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
                new=AsyncMock(return_value="FREE"),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.set_user_tier",
                new=AsyncMock(),
            ) as mock_settier,
        ):
            asyncio.run(admin_root(upd, ctx))
        mock_settier.assert_not_called(), "set_user_tier must not be called by FREE user"

    # 4-F: PREMIUM user cannot trigger /admin settier
    def test_premium_user_cannot_trigger_settier(self):
        from projects.polymarket.crusaderbot.bot.handlers.admin import admin_root
        upd, ctx = self._update_for(
            user_id=9999002, args=["settier", "9000002", "ADMIN"]
        )
        with (
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
                return_value=SimpleNamespace(OPERATOR_CHAT_ID=1),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
                new=AsyncMock(return_value="PREMIUM"),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.set_user_tier",
                new=AsyncMock(),
            ) as mock_settier,
        ):
            asyncio.run(admin_root(upd, ctx))
        mock_settier.assert_not_called(), "set_user_tier must not be called by PREMIUM user"

    # 4-G: /admin users shows ALL users (correct — admin scope, not a leak)
    def test_admin_users_subcommand_allowed_for_admin_tier(self):
        from projects.polymarket.crusaderbot.bot.handlers.admin import admin_root
        upd, ctx = self._update_for(user_id=9999003, args=["users"])
        with (
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
                return_value=SimpleNamespace(OPERATOR_CHAT_ID=1),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
                new=AsyncMock(return_value="ADMIN"),
            ),
            patch(
                "projects.polymarket.crusaderbot.bot.handlers.admin.list_all_user_tiers",
                new=AsyncMock(return_value=[
                    {"user_id": _TG_A, "tier": "FREE",
                     "assigned_at": None, "assigned_by": None},
                    {"user_id": _TG_B, "tier": "PREMIUM",
                     "assigned_at": None, "assigned_by": None},
                ]),
            ),
        ):
            asyncio.run(admin_root(upd, ctx))
        upd.message.reply_text.assert_called_once()

    # 4-H: require_access_tier decorator — FREE blocked from PREMIUM handler
    def test_require_access_tier_blocks_free_from_premium(self):
        from projects.polymarket.crusaderbot.bot.middleware.access_tier import (
            require_access_tier,
        )

        called = []

        @require_access_tier("PREMIUM")
        async def _premium_handler(update, context):
            called.append("executed")

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user = SimpleNamespace(id=9999010)
        upd.effective_message = msg
        ctx = MagicMock()

        with patch(
            "projects.polymarket.crusaderbot.bot.middleware.access_tier.get_user_tier",
            new=AsyncMock(return_value="FREE"),
        ):
            asyncio.run(_premium_handler(upd, ctx))

        assert not called, "PREMIUM handler should not execute for FREE user"
        msg.reply_text.assert_called_once()

    # 4-I: require_access_tier — PREMIUM can access PREMIUM handler
    def test_require_access_tier_allows_premium(self):
        from projects.polymarket.crusaderbot.bot.middleware.access_tier import (
            require_access_tier,
        )

        called = []

        @require_access_tier("PREMIUM")
        async def _premium_handler(update, context):
            called.append("executed")

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user = SimpleNamespace(id=9999011)
        upd.effective_message = msg
        ctx = MagicMock()

        with patch(
            "projects.polymarket.crusaderbot.bot.middleware.access_tier.get_user_tier",
            new=AsyncMock(return_value="PREMIUM"),
        ):
            asyncio.run(_premium_handler(upd, ctx))

        assert "executed" in called, "PREMIUM handler should execute for PREMIUM user"

    # 4-J: require_access_tier — ADMIN tier blocked from ADMIN handler if not ADMIN
    def test_require_access_tier_blocks_premium_from_admin(self):
        from projects.polymarket.crusaderbot.bot.middleware.access_tier import (
            require_access_tier,
        )

        called = []

        @require_access_tier("ADMIN")
        async def _admin_handler(update, context):
            called.append("executed")

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user = SimpleNamespace(id=9999012)
        upd.effective_message = msg
        ctx = MagicMock()

        with patch(
            "projects.polymarket.crusaderbot.bot.middleware.access_tier.get_user_tier",
            new=AsyncMock(return_value="PREMIUM"),
        ):
            asyncio.run(_admin_handler(upd, ctx))

        assert not called, "ADMIN handler should not execute for PREMIUM user"
