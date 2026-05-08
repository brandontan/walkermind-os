"""Tests for the Tier 2 operator seeder.

The seeder is wired into the Fly release_command, so its failure modes
matter as much as its happy path: a missing or malformed
``ADMIN_USER_IDS`` value must NOT cause the deploy to roll back, and a
re-run on a database that already has the operators must be a no-op.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.scripts import seed_operator_tier as seed


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _parse_ids
# ---------------------------------------------------------------------------


def test_parse_ids_empty_or_none_returns_empty_list():
    assert seed._parse_ids(None) == []
    assert seed._parse_ids("") == []
    assert seed._parse_ids("   ") == []
    assert seed._parse_ids(",,,") == []


def test_parse_ids_strips_whitespace_and_drops_empty_tokens():
    assert seed._parse_ids(" 123 , 456 ,, 789 ") == [123, 456, 789]


def test_parse_ids_skips_unparseable_tokens(caplog):
    with caplog.at_level("WARNING"):
        out = seed._parse_ids("123,not-an-int,456")
    assert out == [123, 456]
    assert any("not-an-int" in rec.getMessage() for rec in caplog.records)


def test_parse_ids_handles_negative_ids():
    """Telegram supplies positive ids; negative ids appear in the demo
    seeder. The parser must still accept them — validation belongs at
    the caller, not here.
    """
    assert seed._parse_ids("-1, -2, 3") == [-1, -2, 3]


# ---------------------------------------------------------------------------
# _seed_one
# ---------------------------------------------------------------------------


def test_seed_one_inserts_when_user_missing():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock()

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "inserted"
    assert prev is None
    assert new == seed.OPERATOR_TIER
    # One INSERT was issued (user_settings is provisioned lazily on first read).
    assert conn.execute.await_count == 1
    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO users" in sql
    assert "ON CONFLICT" in sql


def test_seed_one_raises_tier_when_below_threshold():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "uuid-1", "access_tier": 1})
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=seed.OPERATOR_TIER)

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "raised"
    assert prev == 1
    assert new == seed.OPERATOR_TIER
    sql = conn.fetchval.await_args.args[0]
    assert "UPDATE users SET access_tier=GREATEST" in sql, (
        "UPDATE must be GREATEST(access_tier, target) — see "
        "test_seed_one_does_not_demote_concurrent_promotion for the "
        "race-condition rationale"
    )
    assert "RETURNING access_tier" in sql


def test_seed_one_does_not_demote_concurrent_promotion():
    """Race: the previous app version is still serving the DB during a
    Fly release. Our SELECT sees ``access_tier=1`` but a concurrent
    process promotes the operator to Tier 4 before our UPDATE lands.
    The GREATEST clause must keep the higher tier and our action
    label must report "noop" (the script did not lower the value).
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={"id": "uuid-1", "access_tier": 1},
    )
    # GREATEST(4, 2) = 4 — the concurrent promotion wins.
    conn.fetchval = AsyncMock(return_value=4)

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "noop", (
        "concurrent promote must produce a noop label so the audit "
        "log does not falsely attribute the change to this script"
    )
    assert prev == 1
    assert new == 4


def test_seed_one_handles_returning_none_after_concurrent_delete():
    """If the row is DELETEd between our SELECT and UPDATE, RETURNING
    yields no row and ``fetchval`` returns ``None``. The seeder must
    fall back to the pre-update tier so the audit row stays consistent.
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={"id": "uuid-1", "access_tier": 1},
    )
    conn.fetchval = AsyncMock(return_value=None)

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "noop"
    assert prev == 1
    assert new == 1


def test_seed_one_noop_when_already_at_or_above_tier():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "uuid-1", "access_tier": 2})
    conn.execute = AsyncMock()

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "noop"
    assert prev == 2
    assert new == 2
    conn.execute.assert_not_awaited()


def test_seed_one_noop_does_not_demote_higher_tier():
    """A Tier 4 (live-eligible) operator must not be demoted to Tier 2."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "uuid-1", "access_tier": 4})
    conn.execute = AsyncMock()

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "noop"
    assert prev == 4
    assert new == 4
    conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# _write_audit
# ---------------------------------------------------------------------------


class _NoopTx:
    """Async context manager mock that simulates asyncpg's nested
    transaction (a SAVEPOINT). ``__aexit__`` returns False so any
    exception raised inside the context propagates outward — exactly
    what real asyncpg does with ``Transaction.__aexit__``.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _conn_with_tx(execute_side_effect=None):
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=execute_side_effect)
    conn.transaction = MagicMock(return_value=_NoopTx())
    return conn


def test_write_audit_inserts_into_audit_log():
    conn = _conn_with_tx()

    _run(seed._write_audit(
        conn,
        telegram_user_id=42,
        action="inserted",
        prev_tier=None,
        new_tier=2,
    ))

    conn.execute.assert_awaited_once()
    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO audit.log" in sql


def test_write_audit_uses_nested_transaction_for_savepoint_isolation():
    """The INSERT must run inside ``async with conn.transaction()`` so a
    failed audit row does NOT poison the outer seed transaction.
    PostgreSQL aborts the surrounding transaction after any failed
    statement, so without a savepoint the seeder would fail on every
    subsequent id in the batch with ``current transaction is aborted``.
    """
    conn = _conn_with_tx()

    _run(seed._write_audit(
        conn,
        telegram_user_id=42,
        action="inserted",
        prev_tier=None,
        new_tier=2,
    ))
    assert conn.transaction.call_count == 1, (
        "audit write must enter a nested conn.transaction() so an audit "
        "INSERT failure rolls back to a savepoint"
    )


def test_write_audit_swallows_exceptions(caplog):
    """Audit failure must never propagate out of the seeder."""
    conn = _conn_with_tx(execute_side_effect=RuntimeError("audit table missing"))

    with caplog.at_level("WARNING"):
        _run(seed._write_audit(
            conn,
            telegram_user_id=42,
            action="inserted",
            prev_tier=None,
            new_tier=2,
        ))
    assert any("audit write failed" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# seed (transactional driver)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_conn_factory():
    """Patch ``asyncpg.connect`` to return a controllable mock connection."""

    def _factory(initial_rows: dict[int, int | None]):
        """``initial_rows`` maps telegram_id -> existing access_tier (or None)."""
        conn = MagicMock()
        conn.close = AsyncMock()

        # Track per-id state across calls (insert/raise should mutate state).
        state = dict(initial_rows)

        async def _fetchrow(sql, *args):
            tg_id = args[0]
            tier = state.get(tg_id)
            if tier is None:
                return None
            return {"id": f"uuid-{tg_id}", "access_tier": tier}

        async def _execute(sql, *args):
            if "INSERT INTO users" in sql:
                state[args[0]] = seed.OPERATOR_TIER
            return None

        async def _fetchval(sql, *args):
            # The raise path issues an ``UPDATE ... GREATEST RETURNING``
            # so the seeder picks up the actual post-update tier even
            # under a concurrent promotion. Replicate the GREATEST
            # semantics here so tests exercise the same branching the
            # production query would.
            if "UPDATE users SET access_tier=GREATEST" in sql:
                uuid_str = args[0]
                target = args[1]
                if isinstance(uuid_str, str) and uuid_str.startswith("uuid-"):
                    tg = int(uuid_str.removeprefix("uuid-"))
                    current = state.get(tg, 0)
                    new = max(current, target)
                    state[tg] = new
                    return new
            return None

        conn.fetchrow = AsyncMock(side_effect=_fetchrow)
        conn.execute = AsyncMock(side_effect=_execute)
        conn.fetchval = AsyncMock(side_effect=_fetchval)

        # ``conn.transaction()`` must be an async context manager.
        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        conn.transaction = MagicMock(return_value=_Tx())
        return conn

    return _factory


def test_seed_counts_actions_correctly(fake_conn_factory):
    conn = fake_conn_factory({
        100: None,  # missing -> inserted
        200: 1,     # below tier -> raised
        300: 2,     # at tier   -> noop
        400: 4,     # above     -> noop
    })

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        counts = _run(seed.seed("postgresql://x", [100, 200, 300, 400]))

    assert counts == {"inserted": 1, "raised": 1, "noop": 2}
    conn.close.assert_awaited()


def test_seed_runs_each_id_in_single_outer_transaction(fake_conn_factory):
    """A partial DB outage mid-loop must roll the whole batch back so the
    operator sees a clean retry rather than half-applied state. The
    audit writes use nested savepoints on top so an audit failure does
    NOT poison the outer transaction; total ``conn.transaction()``
    calls = 1 outer + N audit savepoints (one per non-noop id).
    """
    conn = fake_conn_factory({100: None, 200: None})

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        _run(seed.seed("postgresql://x", [100, 200]))

    # 1 outer batch transaction + 2 audit savepoints (both ids inserted).
    assert conn.transaction.call_count == 3


def test_seed_outer_transaction_survives_audit_failure(fake_conn_factory):
    """When an audit INSERT raises, the outer seed transaction MUST
    survive (savepoint rolls back, outer continues) and the next id in
    the batch must still be processed. This is the regression Codex
    flagged: without nested transactions PostgreSQL aborts the whole
    txn after the first failed audit row.
    """
    conn = fake_conn_factory({100: None, 200: None})

    # Stash the seeder's normal execute side effect, then wrap it so
    # the audit INSERT for id=100 raises while every other statement
    # behaves normally. The outer txn must keep going; id=200 must
    # still be inserted at Tier 2.
    state = {"audit_calls": 0}
    real_execute = conn.execute.side_effect

    async def _execute_with_audit_failure(sql, *args):
        if "INSERT INTO audit.log" in sql:
            state["audit_calls"] += 1
            if state["audit_calls"] == 1:
                raise RuntimeError("audit table missing — first row only")
            return None
        return await real_execute(sql, *args)

    conn.execute = AsyncMock(side_effect=_execute_with_audit_failure)

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        counts = _run(seed.seed("postgresql://x", [100, 200]))

    # Both ids were inserted at Tier 2 — the audit failure on id=100
    # did NOT prevent id=200 from being processed.
    assert counts == {"inserted": 2, "raised": 0, "noop": 0}
    assert state["audit_calls"] == 2  # both audit writes were attempted


# ---------------------------------------------------------------------------
# _run (env-resolution)
# ---------------------------------------------------------------------------


def test_run_returns_2_when_admin_user_ids_missing(monkeypatch, caplog):
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    with caplog.at_level("WARNING"):
        rc = _run(seed._run())
    assert rc == 2
    assert any(
        "ADMIN_USER_IDS unset" in rec.getMessage() for rec in caplog.records
    )


def test_run_returns_2_when_admin_user_ids_empty(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "   ,  ,")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    rc = _run(seed._run())
    assert rc == 2


def test_run_returns_3_when_database_url_missing(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "123,456")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    rc = _run(seed._run())
    assert rc == 3


def test_run_returns_4_on_db_error(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "123")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    async def _boom(dsn, ids):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(seed, "seed", _boom)
    rc = _run(seed._run())
    assert rc == 4


# ---------------------------------------------------------------------------
# main() — Fly release_command exit-code wrapper
# ---------------------------------------------------------------------------


def test_main_returns_zero_when_inner_run_returns_zero(monkeypatch):
    """Happy path: inner _run returned 0, main returns 0."""

    async def _ok():
        return 0

    monkeypatch.setattr(seed, "_run", _ok)
    assert seed.main() == 0


@pytest.mark.parametrize("inner_rc", [2, 3, 4])
def test_main_swallows_nonzero_inner_run_for_fly_deploy(monkeypatch, caplog, inner_rc):
    """Fly's release_command aborts the deploy on any non-zero exit. The
    seeder's internal failure modes (missing env, missing DSN, DB blip on
    first deploy before migrations) are ALL recoverable without rolling
    back the release, so main() must wrap them to exit 0 and only log
    the inner status code for diagnostics.
    """

    async def _failing():
        return inner_rc

    monkeypatch.setattr(seed, "_run", _failing)
    with caplog.at_level("WARNING"):
        rc = seed.main()
    assert rc == 0, (
        f"main() returned {rc} for inner_rc={inner_rc}; Fly release_command "
        "would have aborted the deploy"
    )
    assert any(
        "exiting 0" in rec.getMessage() for rec in caplog.records
    ), "main() should log the swallowed inner status code at WARNING"


def test_run_returns_0_on_success(monkeypatch, fake_conn_factory):
    monkeypatch.setenv("ADMIN_USER_IDS", "123,456")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    conn = fake_conn_factory({123: None, 456: 1})

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        rc = _run(seed._run())
    assert rc == 0
