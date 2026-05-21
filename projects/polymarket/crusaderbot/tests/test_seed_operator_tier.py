"""Tests for the admin role seeder.

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
    assert seed._parse_ids("-1, -2, 3") == [-1, -2, 3]


# ---------------------------------------------------------------------------
# _seed_one — role-based seeder
# ---------------------------------------------------------------------------


def test_seed_one_inserts_when_user_missing():
    conn = MagicMock()
    # SELECT returns None (no existing row); upsert RETURNING reports a fresh insert.
    conn.fetchrow = AsyncMock(side_effect=[
        None,
        {"role": seed.ADMIN_ROLE, "was_inserted": True},
    ])

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "inserted"
    assert prev is None
    assert new == seed.ADMIN_ROLE
    upsert_sql = conn.fetchrow.await_args_list[1].args[0]
    assert "INSERT INTO users" in upsert_sql
    assert "ON CONFLICT (telegram_user_id) DO UPDATE" in upsert_sql
    assert "SET role = EXCLUDED.role" in upsert_sql
    assert "(xmax = 0) AS was_inserted" in upsert_sql


def test_seed_one_atomic_upsert_handles_concurrent_insert():
    """Race: a concurrent process inserted the row between our SELECT and
    INSERT. The atomic upsert's ``DO UPDATE SET role = EXCLUDED.role``
    promotes the row to admin; ``xmax != 0`` flags the conflict path so
    the audit label is "raised", not "inserted".
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[
        None,
        {"role": seed.ADMIN_ROLE, "was_inserted": False},
    ])

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "raised"
    assert prev is None
    assert new == seed.ADMIN_ROLE


def test_seed_one_promotes_user_to_admin():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "uuid-1", "role": "user"})
    conn.fetchval = AsyncMock(return_value=seed.ADMIN_ROLE)

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "raised"
    assert prev == "user"
    assert new == seed.ADMIN_ROLE
    sql = conn.fetchval.await_args.args[0]
    assert "UPDATE users SET role=$2" in sql
    assert "RETURNING role" in sql


def test_seed_one_handles_returning_none_after_concurrent_delete():
    """If the row is DELETEd between SELECT and UPDATE, RETURNING yields
    no row. The seeder must fall back to the pre-update role for audit
    consistency.
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={"id": "uuid-1", "role": "user"},
    )
    conn.fetchval = AsyncMock(return_value=None)

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "noop"
    assert prev == "user"
    assert new == "user"


def test_seed_one_noop_when_already_admin():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "uuid-1", "role": "admin"})
    conn.execute = AsyncMock()

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "noop"
    assert prev == "admin"
    assert new == "admin"
    conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# _write_audit
# ---------------------------------------------------------------------------


class _NoopTx:
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
        prev_role=None,
        new_role="admin",
    ))

    conn.execute.assert_awaited_once()
    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO audit.log" in sql


def test_write_audit_uses_nested_transaction_for_savepoint_isolation():
    """Audit INSERT runs inside ``async with conn.transaction()`` so a
    failed audit row rolls back to a savepoint instead of poisoning the
    outer seed transaction.
    """
    conn = _conn_with_tx()

    _run(seed._write_audit(
        conn,
        telegram_user_id=42,
        action="inserted",
        prev_role=None,
        new_role="admin",
    ))
    assert conn.transaction.call_count == 1


def test_write_audit_swallows_exceptions(caplog):
    conn = _conn_with_tx(execute_side_effect=RuntimeError("audit table missing"))

    with caplog.at_level("WARNING"):
        _run(seed._write_audit(
            conn,
            telegram_user_id=42,
            action="inserted",
            prev_role=None,
            new_role="admin",
        ))
    assert any("audit write failed" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# seed (transactional driver)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_conn_factory():
    """Patch ``asyncpg.connect`` to return a controllable mock connection."""

    def _factory(initial_rows: dict[int, str | None]):
        """``initial_rows`` maps telegram_id -> existing role (or None for missing)."""
        conn = MagicMock()
        conn.close = AsyncMock()

        state = dict(initial_rows)

        async def _fetchrow(sql, *args):
            if sql.startswith("SELECT id, role FROM users"):
                tg_id = args[0]
                role = state.get(tg_id)
                if role is None:
                    return None
                return {"id": f"uuid-{tg_id}", "role": role}
            if "INSERT INTO users" in sql and "DO UPDATE" in sql:
                tg_id = args[0]
                new_role = args[2]
                pre = state.get(tg_id)
                state[tg_id] = new_role
                return {"role": new_role, "was_inserted": pre is None}
            return None

        async def _execute(sql, *args):
            return None

        async def _fetchval(sql, *args):
            if "UPDATE users SET role=$2" in sql:
                uuid_str = args[0]
                new_role = args[1]
                if isinstance(uuid_str, str) and uuid_str.startswith("uuid-"):
                    tg = int(uuid_str.removeprefix("uuid-"))
                    state[tg] = new_role
                    return new_role
            return None

        conn.fetchrow = AsyncMock(side_effect=_fetchrow)
        conn.execute = AsyncMock(side_effect=_execute)
        conn.fetchval = AsyncMock(side_effect=_fetchval)

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
        100: None,     # missing  -> inserted
        200: "user",   # user     -> raised
        300: "admin",  # admin    -> noop
    })

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        counts = _run(seed.seed("postgresql://x", [100, 200, 300]))

    assert counts == {"inserted": 1, "raised": 1, "noop": 1}
    conn.close.assert_awaited()


def test_seed_runs_each_id_in_single_outer_transaction(fake_conn_factory):
    """Partial DB outage mid-loop rolls the whole batch back. Audit
    writes use nested savepoints on top so an audit failure does NOT
    poison the outer transaction; total ``conn.transaction()`` calls =
    1 outer + N audit savepoints (one per non-noop id).
    """
    conn = fake_conn_factory({100: None, 200: None})

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        _run(seed.seed("postgresql://x", [100, 200]))

    assert conn.transaction.call_count == 3


def test_seed_outer_transaction_survives_audit_failure(fake_conn_factory):
    """An audit INSERT failure must NOT abort the outer seed transaction."""
    conn = fake_conn_factory({100: None, 200: None})

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

    assert counts == {"inserted": 2, "raised": 0, "noop": 0}
    assert state["audit_calls"] == 2


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
    async def _ok():
        return 0

    monkeypatch.setattr(seed, "_run", _ok)
    assert seed.main() == 0


@pytest.mark.parametrize("inner_rc", [2, 3, 4])
def test_main_swallows_nonzero_inner_run_for_fly_deploy(monkeypatch, caplog, inner_rc):
    async def _failing():
        return inner_rc

    monkeypatch.setattr(seed, "_run", _failing)
    with caplog.at_level("WARNING"):
        rc = seed.main()
    assert rc == 0
    assert any("exiting 0" in rec.getMessage() for rec in caplog.records)


def test_run_returns_0_on_success(monkeypatch, fake_conn_factory):
    monkeypatch.setenv("ADMIN_USER_IDS", "123,456")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    conn = fake_conn_factory({123: None, 456: "user"})

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        rc = _run(seed._run())
    assert rc == 0
