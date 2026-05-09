"""Hermetic tests for ``crusaderbot.database`` pool init + ping diagnostics.

Covers two contracts added by the asyncpg + PgBouncer fix:

  * ``init_pool`` MUST pass ``statement_cache_size=0`` to
    ``asyncpg.create_pool`` so prepared-statement names do not collide
    under PgBouncer transaction-pooling multiplexing.
  * ``ping()`` MUST capture the exception class on failure into
    ``last_ping_error()`` so the health endpoint can surface the
    asyncpg class in the Telegram operator alert without a Sentry trip.

No real DB. ``asyncpg.create_pool`` and the returned pool are replaced
by async-context-manager doubles.
"""
from __future__ import annotations

import asyncio
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
    def __init__(self, *, conn: _FakeConn | None = None,
                 acquire_raises: Exception | None = None):
        self._conn = conn or _FakeConn()
        self._acquire_raises = acquire_raises

    def acquire(self) -> _FakeAcquire:
        if self._acquire_raises is not None:
            raise self._acquire_raises
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


# ---------- init_pool: PgBouncer-safe contract ------------------------------


def test_init_pool_passes_statement_cache_size_zero():
    """Required for PgBouncer transaction-pooling compatibility.

    Without ``statement_cache_size=0`` asyncpg caches server-side
    prepared statements by name. PgBouncer multiplexes connections per
    transaction, so the next acquire can land on a different backend
    where that name does not exist — producing the
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
        "server-side prepared statement cache under PgBouncer "
        "transaction-pooling. Found kwargs=%r" % kwargs
    )
    # Defence-in-depth: the rest of the pool contract must remain intact.
    assert kwargs.get("min_size") == 1
    assert kwargs.get("max_size") == 5
    assert kwargs.get("command_timeout") == 30
    assert kwargs.get("dsn") == "postgresql://example/db"


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
    # exc_info is a (type, value, tb) tuple — assert the type matches.
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

    # Stub the three non-DB checks so they return ok=True and don't try
    # to reach Telegram / Alchemy in the test process.
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
