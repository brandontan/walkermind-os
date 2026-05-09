"""Hermetic tests for ``crusaderbot.database`` pool init + ping diagnostics.

Covers the four contracts added by the asyncpg + Supabase Supavisor fix:

  * ``init_pool`` MUST pass ``statement_cache_size=0`` so prepared
    statement names do not collide under transaction-pooling
    multiplexing (Supabase Supavisor port 6543, Fly PgBouncer, etc.).
  * ``init_pool`` MUST pass ``server_settings.application_name`` so the
    bot's connections are identifiable in ``pg_stat_activity``.
  * ``init_pool`` emits a diagnostic warning when ``DATABASE_URL`` host
    matches the Supavisor pattern AND port == 6543 — operators
    correlate this with /health flap events on legacy DSNs.
  * ``ping()`` captures the exception class on failure into
    ``last_ping_error()`` and forwards the structured exception to
    Sentry via ``exc_info=True``.

No real DB. ``asyncpg.create_pool`` and the returned pool are replaced
by async-context-manager doubles.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot import database as db_module


# ---------- Fakes -----------------------------------------------------------


class _FakeConn:
    def __init__(self, *, fetchval_result: Any = 1, raises: Exception | None = None):
        self._fetchval_result = fetchval_result
        self._raises = raises

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self._raises is not None:
            raise self._raises
        return self._fetchval_result


class _FakeAcquire:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


class _FakePool:
    def __init__(self, *, conn: _FakeConn | None = None):
        self._conn = conn or _FakeConn()

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_pool_singleton():
    """Each test gets a fresh module-level pool/last-error state."""
    db_module._pool = None
    db_module._last_ping_error = None
    yield
    db_module._pool = None
    db_module._last_ping_error = None


def _run(coro):
    return asyncio.run(coro)


# ---------- init_pool: Supavisor / PgBouncer-safe contract ------------------


def test_init_pool_passes_statement_cache_size_zero():
    """Required for Supabase Supavisor (and any PgBouncer-style)
    transaction-pooling compatibility.

    Without ``statement_cache_size=0`` asyncpg caches server-side
    prepared statements per backend connection. Supavisor / PgBouncer
    multiplex connections per transaction, so the next acquire can
    land on a different backend where the cached name does not exist —
    surfacing as the
    ``prepared statement "__asyncpg_stmt_*__" does not exist`` /
    DuplicatePreparedStatementError / ProtocolViolationError flap that
    motivated this fix (Sentry DAWN-SNOWFLAKE-1729-G/J/P/Q).
    """
    fake_pool = _FakePool()
    create_pool_mock = AsyncMock(return_value=fake_pool)
    fake_settings = MagicMock(
        DATABASE_URL="postgresql://example/db",
        DB_POOL_MAX=5,
    )
    with patch.object(db_module.asyncpg, "create_pool", new=create_pool_mock), \
         patch.object(db_module, "get_settings", return_value=fake_settings):
        pool = _run(db_module.init_pool())

    assert pool is fake_pool
    create_pool_mock.assert_awaited_once()
    kwargs = create_pool_mock.await_args.kwargs
    assert kwargs.get("statement_cache_size") == 0, (
        "init_pool MUST pass statement_cache_size=0 to disable asyncpg's "
        "server-side prepared statement cache under transaction-pooling. "
        "Found kwargs=%r" % kwargs
    )
    # Defence-in-depth: the rest of the pool contract must remain intact.
    assert kwargs.get("min_size") == 1
    assert kwargs.get("max_size") == 5
    assert kwargs.get("command_timeout") == 30
    assert kwargs.get("dsn") == "postgresql://example/db"


def test_init_pool_passes_application_name_server_setting():
    """``server_settings.application_name`` MUST be set so the bot's
    connections are identifiable in pg_stat_activity (Supabase SQL
    editor / direct Postgres). Without this, every session shows up
    as the asyncpg default and is indistinguishable from psql, the
    Supabase Studio session, or other workloads sharing the project.
    """
    create_pool_mock = AsyncMock(return_value=_FakePool())
    fake_settings = MagicMock(
        DATABASE_URL="postgresql://example/db",
        DB_POOL_MAX=5,
    )
    with patch.object(db_module.asyncpg, "create_pool", new=create_pool_mock), \
         patch.object(db_module, "get_settings", return_value=fake_settings):
        _run(db_module.init_pool())
    kwargs = create_pool_mock.await_args.kwargs
    server_settings = kwargs.get("server_settings")
    assert isinstance(server_settings, dict), (
        f"server_settings must be a dict, got {server_settings!r}"
    )
    assert server_settings.get("application_name") == "crusaderbot", (
        f"application_name must be 'crusaderbot', got {server_settings!r}"
    )


# ---------- Supavisor pooler-awareness diagnostic ---------------------------


def test_init_pool_warns_when_supavisor_transaction_pool(caplog):
    """When DATABASE_URL host contains 'pooler.supabase' AND port is
    6543, init_pool emits an informational WARNING so the operator can
    correlate /health flap events with the DSN topology. The warning
    is NOT a startup blocker.
    """
    create_pool_mock = AsyncMock(return_value=_FakePool())
    fake_settings = MagicMock(
        DATABASE_URL=(
            "postgresql://postgres:pw@aws-0-us-east-1.pooler.supabase.com"
            ":6543/postgres"
        ),
        DB_POOL_MAX=5,
    )
    with caplog.at_level(
        "WARNING", logger="projects.polymarket.crusaderbot.database",
    ):
        with patch.object(
            db_module.asyncpg, "create_pool", new=create_pool_mock,
        ), patch.object(
            db_module, "get_settings", return_value=fake_settings,
        ):
            _run(db_module.init_pool())
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Supavisor transaction pool" in m for m in msgs), (
        f"expected Supavisor transaction-pool warning, got {msgs!r}"
    )
    # Pool init MUST NOT have been blocked.
    create_pool_mock.assert_awaited_once()


def test_init_pool_does_not_warn_for_session_pool_port(caplog):
    """The session pooler (port 5432) is compatible with prepared
    statements and must NOT trigger the warning, even when the host
    matches the Supavisor pattern. Otherwise operators on a healthy
    session-pooled deploy would see a misleading warning every boot.
    """
    create_pool_mock = AsyncMock(return_value=_FakePool())
    fake_settings = MagicMock(
        DATABASE_URL=(
            "postgresql://postgres:pw@aws-0-us-east-1.pooler.supabase.com"
            ":5432/postgres"
        ),
        DB_POOL_MAX=5,
    )
    with caplog.at_level(
        "WARNING", logger="projects.polymarket.crusaderbot.database",
    ):
        with patch.object(
            db_module.asyncpg, "create_pool", new=create_pool_mock,
        ), patch.object(
            db_module, "get_settings", return_value=fake_settings,
        ):
            _run(db_module.init_pool())
    supavisor_warnings = [
        r for r in caplog.records
        if "Supavisor transaction pool" in r.getMessage()
    ]
    assert supavisor_warnings == [], (
        f"port 5432 must not trigger the transaction-pool warning, got "
        f"{[w.getMessage() for w in supavisor_warnings]!r}"
    )


def test_init_pool_does_not_warn_for_non_supabase_host(caplog):
    """Non-Supabase hosts (Fly Postgres, RDS, etc.) must not get the
    Supabase-specific diagnostic — the warning is host-aware on
    purpose so the message stays actionable.
    """
    create_pool_mock = AsyncMock(return_value=_FakePool())
    fake_settings = MagicMock(
        DATABASE_URL="postgresql://postgres:pw@some-other-host:6543/db",
        DB_POOL_MAX=5,
    )
    with caplog.at_level(
        "WARNING", logger="projects.polymarket.crusaderbot.database",
    ):
        with patch.object(
            db_module.asyncpg, "create_pool", new=create_pool_mock,
        ), patch.object(
            db_module, "get_settings", return_value=fake_settings,
        ):
            _run(db_module.init_pool())
    supavisor_warnings = [
        r for r in caplog.records
        if "Supavisor transaction pool" in r.getMessage()
    ]
    assert supavisor_warnings == []


def test_init_pool_diagnostic_does_not_crash_on_malformed_dsn(caplog):
    """A garbage DSN must not crash the diagnostic helper — the pool
    init itself will fail later on, but the diagnostic must be a
    noop on parse failure so it never becomes a boot blocker.
    """
    create_pool_mock = AsyncMock(return_value=_FakePool())
    fake_settings = MagicMock(
        DATABASE_URL="not-a-real-dsn",
        DB_POOL_MAX=5,
    )
    with patch.object(
        db_module.asyncpg, "create_pool", new=create_pool_mock,
    ), patch.object(
        db_module, "get_settings", return_value=fake_settings,
    ):
        # Must not raise.
        _run(db_module.init_pool())


# ---------- ping(): exception class surfaced via last_ping_error() ----------


def test_ping_success_clears_last_error():
    """A successful ping resets ``last_ping_error()`` to None."""
    # Pre-populate a stale error to prove ping clears it on success.
    db_module._last_ping_error = "PreviousError"
    fake_pool = _FakePool(conn=_FakeConn(fetchval_result=1))
    with patch.object(db_module, "init_pool", new=AsyncMock(return_value=fake_pool)):
        ok = _run(db_module.ping())
    assert ok is True
    assert db_module.last_ping_error() is None


def test_ping_failure_records_exception_class_name():
    """Failure path records the exception class name (not the message)
    so the operator alert never embeds raw ``str(exc)`` content.
    """
    class FakeDuplicatePreparedStatementError(Exception):
        pass

    fake_pool = _FakePool(conn=_FakeConn(
        raises=FakeDuplicatePreparedStatementError(
            "prepared statement \"__asyncpg_stmt_e7__\" does not exist"
        ),
    ))
    with patch.object(db_module, "init_pool", new=AsyncMock(return_value=fake_pool)):
        ok = _run(db_module.ping())
    assert ok is False
    assert db_module.last_ping_error() == "FakeDuplicatePreparedStatementError"


def test_ping_failure_logs_with_exc_info(caplog):
    """``logger.error`` MUST pass ``exc_info=True`` so Sentry receives
    the structured exception (class + traceback + cause chain), not
    just the formatted message string.
    """
    err = RuntimeError("simulated asyncpg fault")
    fake_pool = _FakePool(conn=_FakeConn(raises=err))
    with caplog.at_level(
        "ERROR", logger="projects.polymarket.crusaderbot.database",
    ):
        with patch.object(
            db_module, "init_pool", new=AsyncMock(return_value=fake_pool),
        ):
            ok = _run(db_module.ping())
    assert ok is False
    matching = [r for r in caplog.records if "DB ping failed" in r.getMessage()]
    assert matching, "expected a 'DB ping failed' ERROR record"
    rec = matching[0]
    assert rec.exc_info is not None, (
        "logger.error must be called with exc_info=True so Sentry receives "
        "the structured exception"
    )
    assert rec.exc_info[0] is RuntimeError


def test_check_database_surfaces_exception_class_in_health_reason():
    """End-to-end: a ping failure surfaces the asyncpg class name in
    the ``checks["database"]`` string returned by ``run_health_checks``.
    Operators read this string in the Telegram alert; without it they
    were stuck with the generic ``"reported unhealthy"`` text.
    """
    from projects.polymarket.crusaderbot.monitoring import health as monitoring_health

    class FakePostgresConnectionError(Exception):
        pass

    fake_pool = _FakePool(conn=_FakeConn(
        raises=FakePostgresConnectionError("server closed the connection"),
    ))

    async def _ok() -> bool:
        return True

    with patch.object(
        db_module, "init_pool", new=AsyncMock(return_value=fake_pool),
    ), patch.object(
        monitoring_health, "check_telegram", new=_ok,
    ), patch.object(
        monitoring_health, "check_alchemy_rpc", new=_ok,
    ), patch.object(
        monitoring_health, "check_alchemy_ws", new=_ok,
    ):
        result = _run(monitoring_health.run_health_checks())

    assert result["status"] == "down"
    assert result["ready"] is False
    db_reason = result["checks"]["database"]
    assert db_reason.startswith("error: database reported unhealthy")
    assert "FakePostgresConnectionError" in db_reason, (
        f"expected exception class in reason, got {db_reason!r}"
    )
