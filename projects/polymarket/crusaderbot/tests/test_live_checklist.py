"""Hermetic tests for R12 live activation checklist.

No real DB — ``asyncpg.Pool`` and ``Connection`` are replaced with
async-context-manager doubles. The test grid covers:

  * all required gates passing → ready_for_live
  * each gate failing in isolation → that gate appears in failed_gates
  * partial pass — three env gates plus three of the user gates
  * audit row is written every evaluation
  * audit write failure does NOT raise out of evaluate()
  * render_telegram passes case + numbered fix list case
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.activation import live_checklist as lc


USER_ID = uuid4()


# ---------- Fake asyncpg machinery ------------------------------------------


class FakeConn:
    """Connection stand-in that drives gate-specific reads from a config dict."""

    def __init__(self, *, has_wallet: bool = True, deposit_count: int = 1,
                 strategy_types: list[str] | None = None,
                 risk_profile: str | None = "balanced",
                 two_factor: bool = True,
                 role: str = "admin",
                 user_exists: bool = True) -> None:
        self.has_wallet = has_wallet
        self.deposit_count = deposit_count
        self.strategy_types = (
            ["copy_trade"] if strategy_types is None else list(strategy_types)
        )
        self.risk_profile = risk_profile
        self.two_factor = two_factor
        self.role = role
        self.user_exists = user_exists
        self.audit_inserts: list[tuple] = []

    async def fetchrow(self, query: str, *args: Any):
        if "FROM wallets" in query:
            return {"_": 1} if self.has_wallet else None
        if "FROM user_settings" in query and "strategy_types" in query:
            return {"strategy_types": self.strategy_types}
        if "FROM user_settings" in query and "risk_profile" in query:
            return {"risk_profile": self.risk_profile}
        if "FROM system_settings" in query and "key=$1" in query:
            key = args[0]
            if key.startswith("2fa_enabled:"):
                return {"value": "true" if self.two_factor else "false"}
            return None
        return None

    async def fetchval(self, query: str, *args: Any):
        if "COUNT(*) FROM deposits" in query:
            return self.deposit_count
        if "role FROM users" in query:
            return self.role if self.user_exists else None
        return 0

    async def execute(self, query: str, *args: Any):
        if "INSERT INTO audit.log" in query:
            self.audit_inserts.append(args)
        return "INSERT 0 1"


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


def _settings(*, exec_validated: bool = True, capital_confirmed: bool = True,
              live_enabled: bool = True):
    class _S:
        EXECUTION_PATH_VALIDATED = exec_validated
        CAPITAL_MODE_CONFIRMED = capital_confirmed
        ENABLE_LIVE_TRADING = live_enabled
    return _S()


def _run(conn: FakeConn, settings_obj) -> lc.ChecklistResult:
    pool = FakePool(conn)
    with patch.object(lc, "get_pool", return_value=pool), \
         patch.object(lc, "get_settings", return_value=settings_obj):
        # Patch audit.write into the module's reference so the FakeConn captures it.
        with patch("projects.polymarket.crusaderbot.audit.get_pool", return_value=pool):
            return asyncio.run(lc.evaluate(USER_ID))


# ---------- All-pass and all-fail extremes ----------------------------------


def test_all_eight_gates_pass():
    conn = FakeConn()
    result = _run(conn, _settings())
    assert result.passed is True
    assert result.ready_for_live is True
    assert result.failed_gates == []
    # All eight outcomes recorded in canonical order.
    assert [o.name for o in result.outcomes] == list(lc.GATE_ORDER)
    # Audit row captured.
    matched = [args for args in conn.audit_inserts
               if "live_checklist_evaluated" in args[2]]
    assert len(matched) == 1


def test_all_three_env_gates_fail_alone():
    conn = FakeConn()
    result = _run(conn, _settings(exec_validated=False, capital_confirmed=False,
                                  live_enabled=False))
    assert result.passed is False
    assert lc.GATE_EXECUTION_PATH_VALIDATED in result.failed_gates
    assert lc.GATE_CAPITAL_MODE_CONFIRMED in result.failed_gates
    assert lc.GATE_ENABLE_LIVE_TRADING in result.failed_gates


# ---------- One gate fails per test (isolation grid) ------------------------


def test_deposit_is_not_a_gate():
    """live-mode-truth (owner 2026-06-11): switching to live must NOT require
    a prior deposit — users switch first and deposit after. The bot auto-stops
    on the switch and risk-gate step 15 rejects any live trade while the real
    deposited balance is zero, so removing this gate cannot let an unfunded
    account trade. Pin the absence so the gate cannot silently come back."""
    conn = FakeConn(has_wallet=False, deposit_count=0)
    r = _run(conn, _settings())
    assert r.passed is True
    assert "active_subaccount_with_deposit" not in r.failed_gates
    assert not hasattr(lc, "GATE_ACTIVE_SUBACCOUNT")
    assert len(lc.GATE_ORDER) == 5


def test_strategy_gate_fails_when_empty():
    conn = FakeConn(strategy_types=[])
    r = _run(conn, _settings())
    assert lc.GATE_STRATEGY_CONFIGURED in r.failed_gates


def test_risk_profile_gate_fails_when_blank():
    conn = FakeConn(risk_profile=" ")
    r = _run(conn, _settings())
    assert lc.GATE_RISK_PROFILE_CONFIGURED in r.failed_gates


def test_two_factor_and_admin_approval_are_not_hard_gates():
    conn = FakeConn(two_factor=False, role="user", user_exists=False)
    r = _run(conn, _settings())
    assert r.passed is True
    assert not hasattr(lc, "GATE_TWO_FACTOR_SETUP")
    assert not hasattr(lc, "GATE_OPERATOR_ALLOWLIST")
    assert "two_factor_setup_complete" not in r.failed_gates
    assert "operator_allowlist_approved" not in r.failed_gates


# ---------- Partial pass mix ------------------------------------------------


def test_partial_pass_user_required_gate_only():
    # 2FA/admin approval are not hard gates; required strategy/risk gates remain.
    conn = FakeConn(has_wallet=False, two_factor=False, role="user", strategy_types=[])
    r = _run(conn, _settings())
    assert r.passed is False
    assert lc.GATE_STRATEGY_CONFIGURED in r.failed_gates
    assert "two_factor_setup_complete" not in r.failed_gates
    assert "operator_allowlist_approved" not in r.failed_gates
    # Env gates must NOT be in failed list — they passed.
    assert lc.GATE_EXECUTION_PATH_VALIDATED not in r.failed_gates
    assert lc.GATE_CAPITAL_MODE_CONFIRMED not in r.failed_gates
    assert lc.GATE_ENABLE_LIVE_TRADING not in r.failed_gates


# ---------- Audit + render --------------------------------------------------


def test_audit_failure_does_not_break_evaluate():
    conn = FakeConn()
    pool = FakePool(conn)
    with patch.object(lc, "get_pool", return_value=pool), \
         patch.object(lc, "get_settings", return_value=_settings()), \
         patch.object(lc.audit, "write",
                      AsyncMock(side_effect=RuntimeError("audit blew up"))):
        result = asyncio.run(lc.evaluate(USER_ID))
    assert result.passed is True


def test_render_telegram_passed_message():
    result = lc.ChecklistResult(
        passed=True, failed_gates=[], ready_for_live=True,
        outcomes=[lc.GateOutcome(name=n, ok=True) for n in lc.GATE_ORDER],
    )
    out = lc.render_telegram(result)
    assert "Live trading ready" in out
    assert "CONFIRM" in out


def test_render_telegram_failed_message_lists_each_failure_in_order():
    failed = [lc.GATE_EXECUTION_PATH_VALIDATED, lc.GATE_STRATEGY_CONFIGURED]
    outcomes = [
        lc.GateOutcome(name=n, ok=(n not in failed))
        for n in lc.GATE_ORDER
    ]
    result = lc.ChecklistResult(
        passed=False, failed_gates=failed, ready_for_live=False,
        outcomes=outcomes,
    )
    out = lc.render_telegram(result)
    assert "not yet ready" in out
    # Failed gates must appear in canonical (gate-order) sequence,
    # numbered 1, 2, …
    idx_env = out.index(lc.GATE_EXECUTION_PATH_VALIDATED)
    idx_strategy = out.index(lc.GATE_STRATEGY_CONFIGURED)
    assert idx_env < idx_strategy
    assert "1." in out and "2." in out


def test_render_telegram_wraps_gate_names_in_code_tags():
    # Gate identifiers contain underscores; HTML <code> tags preserve them
    # literally and are safe in Telegram HTML mode.
    failed = [lc.GATE_STRATEGY_CONFIGURED, lc.GATE_RISK_PROFILE_CONFIGURED]
    outcomes = [
        lc.GateOutcome(name=n, ok=(n not in failed))
        for n in lc.GATE_ORDER
    ]
    result = lc.ChecklistResult(
        passed=False, failed_gates=failed, ready_for_live=False,
        outcomes=outcomes,
    )
    out = lc.render_telegram(result)
    for name in failed:
        assert f"<code>{name}</code>" in out
        assert f"*{name}*" not in out


def test_gate_fix_hint_known_name_returns_string():
    assert lc.gate_fix_hint(lc.GATE_RISK_PROFILE_CONFIGURED)
    assert lc.gate_fix_hint("nonexistent_gate") is None
