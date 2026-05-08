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

    action, prev, new = _run(seed._seed_one(conn, 123))

    assert action == "raised"
    assert prev == 1
    assert new == seed.OPERATOR_TIER
    sql = conn.execute.await_args.args[0]
    assert "UPDATE users SET access_tier" in sql


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


def test_write_audit_inserts_into_audit_log():
    conn = MagicMock()
    conn.execute = AsyncMock()

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


def test_write_audit_swallows_exceptions(caplog):
    """Audit failure must never propagate out of the seeder."""
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=RuntimeError("audit table missing"))

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
            elif "UPDATE users SET access_tier" in sql:
                # args[0] is uuid string in production; we keyed the state on
                # telegram_id so derive it back from the uuid prefix.
                uuid_str = args[0]
                if isinstance(uuid_str, str) and uuid_str.startswith("uuid-"):
                    tg = int(uuid_str.removeprefix("uuid-"))
                    state[tg] = args[1]
            return None

        conn.fetchrow = AsyncMock(side_effect=_fetchrow)
        conn.execute = AsyncMock(side_effect=_execute)

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


def test_seed_runs_each_id_in_single_transaction(fake_conn_factory):
    """A partial DB outage mid-loop must roll the whole batch back so the
    operator sees a clean retry rather than half-applied state.
    """
    conn = fake_conn_factory({100: None, 200: None})

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        _run(seed.seed("postgresql://x", [100, 200]))

    # ``conn.transaction()`` must have been entered exactly once.
    assert conn.transaction.call_count == 1


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


def test_run_returns_0_on_success(monkeypatch, fake_conn_factory):
    monkeypatch.setenv("ADMIN_USER_IDS", "123,456")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    conn = fake_conn_factory({123: None, 456: 1})

    async def _connect(dsn):
        return conn

    with patch("asyncpg.connect", new=_connect):
        rc = _run(seed._run())
    assert rc == 0
