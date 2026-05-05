"""Hermetic tests for R12 live-to-paper fallback.

Coverage matrix:

  * trigger() flips trading_mode='live' → 'paper' for matching user
  * trigger() is idempotent when user already on paper (no audit, no notify)
  * trigger() with unknown user is a no-op
  * trigger() rejects unknown reasons (ValueError)
  * Audit row written with reason + previous_mode
  * Telegram notification fired for trigger
  * Notify failure does NOT raise (logged only)
  * Per-trigger-condition convenience wrappers feed correct reason string
  * trigger_all_live_users cascades a single SQL UPDATE
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import fallback


USER_ID = uuid4()
TG_ID = 999_001


# ---------- Fake asyncpg ----------------------------------------------------


class FakeConn:
    def __init__(self, *, mode: str | None = "live",
                 telegram_id: int | None = TG_ID,
                 user_exists: bool = True,
                 affected_users: list[dict] | None = None) -> None:
        self.mode = mode
        self.telegram_id = telegram_id
        self.user_exists = user_exists
        self.executes: list[tuple[str, tuple]] = []
        self.fetched: list[tuple[str, tuple]] = []
        self.audit_rows: list[tuple] = []
        self.affected_users = affected_users or []

    async def fetchrow(self, query: str, *args: Any):
        self.fetched.append((query, args))
        if "JOIN users" in query and "user_settings" in query:
            if not self.user_exists:
                return None
            return {"mode": self.mode, "tg_id": self.telegram_id}
        return None

    async def fetch(self, query: str, *args: Any):
        self.fetched.append((query, args))
        if "RETURNING s.user_id" in query:
            return self.affected_users
        return []

    async def execute(self, query: str, *args: Any):
        self.executes.append((query, args))
        if "INSERT INTO audit.log" in query:
            self.audit_rows.append(args)
        if "UPDATE user_settings SET trading_mode='paper'" in query and \
                "user_id=$1" in query:
            self.mode = "paper"
        return "OK"

    def transaction(self):
        conn = self

        class _Txn:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, et, e, tb):
                return False

        return _Txn()


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, et, e, tb):
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


def _patches(conn: FakeConn):
    pool = FakePool(conn)
    return [
        patch.object(fallback, "get_pool", return_value=pool),
        patch("projects.polymarket.crusaderbot.audit.get_pool",
              return_value=pool),
        patch.object(fallback.notifications, "send",
                     AsyncMock(return_value=True)),
    ]


def _run(coro, conn: FakeConn):
    patches = _patches(conn)
    for p in patches:
        p.start()
    try:
        return asyncio.run(coro)
    finally:
        for p in patches:
            p.stop()


# ---------- Single-user trigger --------------------------------------------


def test_trigger_flips_live_user_to_paper():
    conn = FakeConn(mode="live")
    out = _run(
        fallback.trigger(USER_ID, fallback.REASON_CLOB_NON_RECOVERABLE),
        conn,
    )
    assert out["changed"] is True
    assert out["previous_mode"] == "live"
    update_hits = [q for q, _ in conn.executes
                   if "UPDATE user_settings" in q
                   and "trading_mode='paper'" in q]
    assert len(update_hits) == 1
    audit_hits = [args for args in conn.audit_rows
                  if "live_to_paper_fallback" in args[2]]
    assert len(audit_hits) == 1


def test_trigger_idempotent_when_already_paper():
    conn = FakeConn(mode="paper")
    out = _run(
        fallback.trigger(USER_ID, fallback.REASON_LIVE_GUARD_UNSET),
        conn,
    )
    assert out == {"changed": False, "previous_mode": "paper"}
    # No UPDATE, no audit row when no change.
    update_hits = [q for q, _ in conn.executes
                   if "UPDATE user_settings" in q]
    assert update_hits == []
    assert conn.audit_rows == []


def test_trigger_no_user_returns_unchanged():
    conn = FakeConn(user_exists=False)
    out = _run(
        fallback.trigger(USER_ID, fallback.REASON_CLOB_NON_RECOVERABLE),
        conn,
    )
    assert out == {"changed": False, "previous_mode": None}


def test_trigger_rejects_invalid_reason():
    with pytest.raises(ValueError):
        asyncio.run(fallback.trigger(USER_ID, "made_up_reason"))


def test_trigger_audit_payload_includes_reason_and_previous_mode():
    conn = FakeConn(mode="live")
    _run(
        fallback.trigger(USER_ID, fallback.REASON_RISK_HALT_KILL_SWITCH),
        conn,
    )
    # audit.log INSERT receives (user_id, actor_role, action, payload_json).
    assert conn.audit_rows
    args = conn.audit_rows[0]
    payload_json = args[3]
    assert fallback.REASON_RISK_HALT_KILL_SWITCH in payload_json
    assert "live" in payload_json


def test_trigger_notify_failure_does_not_raise():
    conn = FakeConn(mode="live")
    pool = FakePool(conn)
    with patch.object(fallback, "get_pool", return_value=pool), \
         patch("projects.polymarket.crusaderbot.audit.get_pool",
               return_value=pool), \
         patch.object(fallback.notifications, "send",
                      AsyncMock(side_effect=RuntimeError("tg down"))):
        out = asyncio.run(fallback.trigger(
            USER_ID, fallback.REASON_LIVE_GUARD_UNSET,
        ))
    assert out["changed"] is True


# ---------- Each of the four trigger conditions -----------------------------


def test_clob_error_wrapper_uses_correct_reason():
    conn = FakeConn(mode="live")
    _run(fallback.trigger_for_clob_error(USER_ID), conn)
    payload_json = conn.audit_rows[0][3]
    assert fallback.REASON_CLOB_NON_RECOVERABLE in payload_json


def test_kill_switch_wrapper_uses_correct_reason():
    conn = FakeConn(mode="live")
    _run(fallback.trigger_for_kill_switch_halt(USER_ID), conn)
    payload_json = conn.audit_rows[0][3]
    assert fallback.REASON_RISK_HALT_KILL_SWITCH in payload_json


def test_drawdown_wrapper_uses_correct_reason():
    conn = FakeConn(mode="live")
    _run(fallback.trigger_for_drawdown_halt(USER_ID), conn)
    payload_json = conn.audit_rows[0][3]
    assert fallback.REASON_RISK_HALT_DRAWDOWN in payload_json


def test_live_guard_unset_wrapper_uses_correct_reason():
    conn = FakeConn(mode="live")
    _run(fallback.trigger_for_live_guard_unset(USER_ID), conn)
    payload_json = conn.audit_rows[0][3]
    assert fallback.REASON_LIVE_GUARD_UNSET in payload_json


# ---------- System-wide cascade --------------------------------------------


def test_trigger_all_live_users_zero_affected_returns_zero():
    conn = FakeConn(affected_users=[])
    out = _run(
        fallback.trigger_all_live_users(fallback.REASON_KILL_SWITCH_SYSTEM),
        conn,
    )
    assert out == {"changed": 0}


def test_gate_step13_silent_downgrade_triggers_live_guard_unset_fallback():
    """Codex P1 regression: when the gate silently downgrades a live user
    to paper because the global activation guards are off, the user's
    user_settings.trading_mode must NOT remain 'live' — otherwise
    re-enabling the global flags later resumes live routing without
    forcing /live_checklist + CONFIRM.

    This test exercises the step-13 ``live_requested_but_guards_failed``
    branch in :func:`projects.polymarket.crusaderbot.domain.risk.gate.evaluate`
    and verifies it now invokes ``fallback.trigger_for_live_guard_unset``.
    """
    import asyncio as _asyncio
    from datetime import datetime, timezone
    from decimal import Decimal as D
    from uuid import uuid4 as _uuid4

    from projects.polymarket.crusaderbot.domain.risk import gate
    from projects.polymarket.crusaderbot.domain.risk import constants as K

    user_id = _uuid4()

    class _RiskLogConn:
        async def execute(self, q, *a):
            return "OK"
        async def fetchrow(self, q, *a):
            return None
        async def fetchval(self, q, *a):
            return 0

    class _Acquire:
        def __init__(self, c): self.c = c
        async def __aenter__(self): return self.c
        async def __aexit__(self, *_): return False

    class _Pool:
        def acquire(self): return _Acquire(_RiskLogConn())

    ctx = gate.GateContext(
        user_id=user_id,
        telegram_user_id=42,
        access_tier=4,
        auto_trade_on=True,
        paused=False,
        market_id="m1",
        side="yes",
        proposed_size_usdc=D("10"),
        proposed_price=0.5,
        market_liquidity=1_000_000,
        market_status="active",
        edge_bps=1000,
        signal_ts=datetime.now(timezone.utc),
        idempotency_key="idem-1",
        strategy_type=next(iter(K.STRATEGY_AVAILABILITY)),
        risk_profile=K.STRATEGY_AVAILABILITY[
            next(iter(K.STRATEGY_AVAILABILITY))
        ][0],
        daily_loss_override=None,
        trading_mode="live",
    )

    class _Settings:
        # Global activation guards are OFF — the user's configured live
        # mode must therefore be silently downgraded by step 13.
        ENABLE_LIVE_TRADING = False
        EXECUTION_PATH_VALIDATED = False
        CAPITAL_MODE_CONFIRMED = False

    trigger_calls: list = []

    async def fake_trigger(uid):
        trigger_calls.append(uid)
        return {"changed": True, "previous_mode": "live"}

    with patch.object(gate, "get_pool", return_value=_Pool()), \
         patch.object(gate, "kill_switch_is_active",
                      AsyncMock(return_value=False)), \
         patch.object(gate, "daily_pnl",
                      AsyncMock(return_value=D("0"))), \
         patch.object(gate, "_max_drawdown_breached",
                      AsyncMock(return_value=False)), \
         patch.object(gate, "_open_position_count",
                      AsyncMock(return_value=0)), \
         patch.object(gate, "get_balance",
                      AsyncMock(return_value=D("100"))), \
         patch.object(gate, "_open_exposure",
                      AsyncMock(return_value=D("0"))), \
         patch.object(gate, "_idempotent_already_seen",
                      AsyncMock(return_value=False)), \
         patch.object(gate, "_recent_dup_market_trade",
                      AsyncMock(return_value=False)), \
         patch.object(gate, "_record_idempotency",
                      AsyncMock(return_value=None)), \
         patch("projects.polymarket.crusaderbot.config.get_settings",
               return_value=_Settings()), \
         patch.object(gate.live_fallback, "trigger_for_live_guard_unset",
                      side_effect=fake_trigger):
        result = _asyncio.run(gate.evaluate(ctx))

    # Gate still approves (downgraded to paper), but the fallback MUST
    # have fired so the user's persisted trading_mode flips off live.
    assert result.approved is True
    assert result.chosen_mode == "paper"
    assert trigger_calls == [user_id], (
        "step-13 silent downgrade must trigger live_guard_unset fallback"
    )


def test_trigger_all_live_users_writes_audit_per_user():
    affected = [
        {"user_id": uuid4(), "telegram_user_id": 1001},
        {"user_id": uuid4(), "telegram_user_id": 1002},
        {"user_id": uuid4(), "telegram_user_id": None},
    ]
    conn = FakeConn(affected_users=affected)
    out = _run(
        fallback.trigger_all_live_users(fallback.REASON_KILL_SWITCH_SYSTEM),
        conn,
    )
    assert out == {"changed": 3}
    # One audit row per affected user.
    assert len(conn.audit_rows) == 3
    for args in conn.audit_rows:
        payload_json = args[3]
        assert fallback.REASON_KILL_SWITCH_SYSTEM in payload_json
        assert "cascade" in payload_json
