"""Nightly logical deposit sweep — correct count + audit breadcrumb.

Regression: the old ``UPDATE ... RETURNING 1`` + ``fetchval`` always
logged 1/None, never the true number of swept rows (a silent
observability failure). The sweep now wraps the UPDATE in a CTE and
COUNT(*)s it inside a transaction, and writes an audit row.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot import scheduler


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _Conn:
    def __init__(self, count: int) -> None:
        self._count = count
        self.fetchval = AsyncMock(return_value=count)

    def transaction(self):
        return _Txn()


class _Acq:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        return None


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self):
        return _Acq(self._conn)


class _LogicalSettings:
    """Guards OFF → sweep_deposits takes the logical (accounting-only) branch."""
    EXECUTION_PATH_VALIDATED = False
    SWEEP_ONCHAIN_ENABLED = False


def _run_sweep(count: int) -> AsyncMock:
    conn = _Conn(count)
    audit_mock = AsyncMock()
    with patch.object(scheduler, "get_pool", return_value=_Pool(conn)), \
         patch.object(scheduler, "get_settings", return_value=_LogicalSettings()), \
         patch.object(scheduler.audit, "write", new=audit_mock):
        asyncio.run(scheduler.sweep_deposits())
    return audit_mock, conn


def test_sweep_logs_true_count_and_audits():
    audit_mock, conn = _run_sweep(7)
    conn.fetchval.assert_awaited_once()
    sql = conn.fetchval.call_args[0][0]
    assert "COUNT(*)" in sql and "WITH u AS" in sql
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "deposit_sweep"
    assert kwargs["payload"] == {"count": 7}
    assert kwargs["actor_role"] == "bot"


def test_sweep_zero_rows_still_audits_zero():
    audit_mock, _ = _run_sweep(0)
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["payload"] == {"count": 0}


# ── on-chain sweep (LIVE only; double-gated) ─────────────────────────────────

import uuid as _uuid
from decimal import Decimal


class _OnchainSettings:
    EXECUTION_PATH_VALIDATED = True
    SWEEP_ONCHAIN_ENABLED = True


class _OnchainConn:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.executed: list[tuple] = []

    async def fetch(self, _sql, *_a):
        return self._rows

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"


def test_sweep_usdc_blocked_when_disabled():
    """sweep_usdc_to_master refuses before signing unless both flags are ON."""
    from projects.polymarket.crusaderbot.integrations import polygon_usdc

    class _Off:
        EXECUTION_PATH_VALIDATED = True
        SWEEP_ONCHAIN_ENABLED = False

    async def _go():
        with patch.object(polygon_usdc, "get_settings", return_value=_Off()):
            try:
                await polygon_usdc.sweep_usdc_to_master(
                    "0xAbCd1234567890EF1234567890abcdef12345678", "0xpk"
                )
            except polygon_usdc.PreflightError as exc:
                assert "SWEEP_ONCHAIN_ENABLED" in str(exc)
                return True
            return False

    assert asyncio.run(_go()) is True


def test_onchain_sweep_marks_swept_after_confirm():
    """Each user wallet swept on-chain → that user's deposits marked swept + audited."""
    from projects.polymarket.crusaderbot import scheduler as sched
    from projects.polymarket.crusaderbot.integrations import polygon_usdc
    from projects.polymarket.crusaderbot.wallet import vault

    uid = _uuid.uuid4()
    rows = [{"user_id": uid, "deposit_address": "0xAbCd1234567890EF1234567890abcdef12345678"}]
    conn = _OnchainConn(rows)
    audit_mock = AsyncMock()

    with patch.object(sched, "get_settings", return_value=_OnchainSettings()), \
         patch.object(sched, "get_pool", return_value=_Pool(conn)), \
         patch.object(vault, "get_decrypted_pk", AsyncMock(return_value="0xpk")), \
         patch.object(polygon_usdc, "sweep_usdc_to_master",
                      AsyncMock(return_value={"tx_hash": "0xabc", "amount_usdc": "10"})), \
         patch.object(sched.audit, "write", new=audit_mock):
        asyncio.run(sched.sweep_deposits())

    assert any("UPDATE deposits SET swept=TRUE" in sql for sql, _ in conn.executed)
    assert audit_mock.call_args.kwargs["action"] == "deposit_sweep_onchain"


def test_onchain_sweep_skips_dust_without_marking():
    """A dust-skip result must NOT mark deposits swept."""
    from projects.polymarket.crusaderbot import scheduler as sched
    from projects.polymarket.crusaderbot.integrations import polygon_usdc
    from projects.polymarket.crusaderbot.wallet import vault

    rows = [{"user_id": _uuid.uuid4(), "deposit_address": "0xAbCd1234567890EF1234567890abcdef12345678"}]
    conn = _OnchainConn(rows)

    with patch.object(sched, "get_settings", return_value=_OnchainSettings()), \
         patch.object(sched, "get_pool", return_value=_Pool(conn)), \
         patch.object(vault, "get_decrypted_pk", AsyncMock(return_value="0xpk")), \
         patch.object(polygon_usdc, "sweep_usdc_to_master",
                      AsyncMock(return_value={"skipped": True, "reason": "dust"})), \
         patch.object(sched.audit, "write", new=AsyncMock()):
        asyncio.run(sched.sweep_deposits())

    assert conn.executed == []  # nothing marked swept


def test_onchain_sweep_continues_on_user_failure():
    """One failing wallet is logged and skipped; the rest still process."""
    from projects.polymarket.crusaderbot import scheduler as sched
    from projects.polymarket.crusaderbot.integrations import polygon_usdc
    from projects.polymarket.crusaderbot.wallet import vault

    good = _uuid.uuid4()
    bad = _uuid.uuid4()
    rows = [
        {"user_id": bad, "deposit_address": "0x1111111111111111111111111111111111111111"},
        {"user_id": good, "deposit_address": "0x2222222222222222222222222222222222222222"},
    ]
    conn = _OnchainConn(rows)

    async def _sweep(addr, _pk):
        if addr.startswith("0x1111"):
            raise RuntimeError("rpc boom")
        return {"tx_hash": "0xok", "amount_usdc": "5"}

    with patch.object(sched, "get_settings", return_value=_OnchainSettings()), \
         patch.object(sched, "get_pool", return_value=_Pool(conn)), \
         patch.object(vault, "get_decrypted_pk", AsyncMock(return_value="0xpk")), \
         patch.object(polygon_usdc, "sweep_usdc_to_master", _sweep), \
         patch.object(sched.audit, "write", new=AsyncMock()):
        asyncio.run(sched.sweep_deposits())

    # only the good user's deposits marked swept (one UPDATE)
    updates = [a for sql, a in conn.executed if "swept=TRUE" in sql]
    assert len(updates) == 1
    assert updates[0][0] == good
