"""Boot-time live-execution readiness validation (main._validate_live_execution_readiness).

Pins the contract of the startup check added in WARP/root-live-paper-readiness:
misconfigured live-execution flags surface as one loud log line at BOOT, not as
a refused/timed-out first live order. Every check is non-fatal — a broken
validation query or missing binary must never block boot (paper paths stay up).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from projects.polymarket.crusaderbot.main import _validate_live_execution_readiness


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        USE_RUST_SIDECAR=False,
        RUST_SIDECAR_PATH="/nonexistent/order-sidecar",
        USE_PER_USER_EXECUTION=False,
        ENABLE_LIVE_TRADING=False,
        AUTO_REDEEM_ENABLED=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeConn:
    def __init__(self, fetchval_result=0, fetchval_exc: Exception | None = None):
        self._result = fetchval_result
        self._exc = fetchval_exc
        self.queries: list[str] = []

    async def fetchval(self, query: str, *args):
        self.queries.append(query)
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_all_flags_off_reports_nothing():
    conn = _FakeConn()
    problems = await _validate_live_execution_readiness(_settings(), _FakePool(conn))
    assert problems == []
    assert conn.queries == []  # no DB touch when per-user execution is off


@pytest.mark.asyncio
async def test_sidecar_flag_with_empty_path_is_reported():
    s = _settings(USE_RUST_SIDECAR=True, RUST_SIDECAR_PATH="")
    problems = await _validate_live_execution_readiness(s, _FakePool(_FakeConn()))
    assert len(problems) == 1
    assert "RUST_SIDECAR_PATH is not configured" in problems[0]


@pytest.mark.asyncio
async def test_sidecar_flag_with_missing_binary_is_reported():
    s = _settings(USE_RUST_SIDECAR=True, RUST_SIDECAR_PATH="/nonexistent/order-sidecar")
    problems = await _validate_live_execution_readiness(s, _FakePool(_FakeConn()))
    assert len(problems) == 1
    assert "/nonexistent/order-sidecar" in problems[0]
    assert "USE_RUST_SIDECAR" in problems[0]


@pytest.mark.asyncio
async def test_sidecar_flag_with_executable_binary_is_clean(tmp_path):
    binary = tmp_path / "order-sidecar"
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o755)
    s = _settings(USE_RUST_SIDECAR=True, RUST_SIDECAR_PATH=str(binary))
    problems = await _validate_live_execution_readiness(s, _FakePool(_FakeConn()))
    assert problems == []


@pytest.mark.asyncio
async def test_sidecar_flag_with_non_executable_binary_is_reported(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root bypasses file mode checks — os.access X_OK is always true")
    binary = tmp_path / "order-sidecar"
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o644)
    s = _settings(USE_RUST_SIDECAR=True, RUST_SIDECAR_PATH=str(binary))
    problems = await _validate_live_execution_readiness(s, _FakePool(_FakeConn()))
    assert len(problems) == 1
    assert "not" in problems[0] and "executable" in problems[0]


@pytest.mark.asyncio
async def test_per_user_execution_with_null_wallets_is_reported():
    conn = _FakeConn(fetchval_result=3)
    s = _settings(USE_PER_USER_EXECUTION=True)
    problems = await _validate_live_execution_readiness(s, _FakePool(conn))
    assert len(problems) == 1
    assert "3 wallet(s)" in problems[0]
    assert "backfill_deposit_wallets" in problems[0]
    assert any("polymarket_deposit_wallet IS NULL" in q for q in conn.queries)


@pytest.mark.asyncio
async def test_per_user_execution_fully_backfilled_is_clean():
    conn = _FakeConn(fetchval_result=0)
    s = _settings(USE_PER_USER_EXECUTION=True)
    problems = await _validate_live_execution_readiness(s, _FakePool(conn))
    assert problems == []


@pytest.mark.asyncio
async def test_per_user_execution_query_failure_never_blocks_boot(caplog):
    conn = _FakeConn(fetchval_exc=RuntimeError("db down"))
    s = _settings(USE_PER_USER_EXECUTION=True)
    with caplog.at_level("WARNING", logger="crusaderbot"):
        problems = await _validate_live_execution_readiness(s, _FakePool(conn))
    assert problems == []  # check skipped, not failed
    assert any("backfill check skipped" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_live_with_auto_redeem_warns_but_is_not_a_problem(caplog):
    s = _settings(ENABLE_LIVE_TRADING=True, AUTO_REDEEM_ENABLED=True)
    with caplog.at_level("WARNING", logger="crusaderbot"):
        problems = await _validate_live_execution_readiness(s, _FakePool(_FakeConn()))
    assert problems == []
    assert any("AUTO_REDEEM_ENABLED" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_problems_are_logged_as_errors(caplog, tmp_path):
    s = _settings(USE_RUST_SIDECAR=True, RUST_SIDECAR_PATH=str(tmp_path / "missing"))
    with caplog.at_level("ERROR", logger="crusaderbot"):
        problems = await _validate_live_execution_readiness(s, _FakePool(_FakeConn()))
    assert len(problems) == 1
    assert any(
        r.levelname == "ERROR" and "live execution readiness" in r.message
        for r in caplog.records
    )
