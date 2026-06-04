"""WARP-69 — per-user autonomous auto-trade loop: hardening invariants.

This lane is an audit + hardening pass on the EXISTING autonomous loop
(``signal_scan_job.run_once`` → existing selection path → 15-step risk gate →
paper execution), gated per-user by ``users.auto_trade_on`` (default FALSE).
It does NOT introduce a parallel ``AUTO_TRADE_ENABLED`` flag — ``auto_trade_on``
is the single canonical opt-in.

These tests pin the three safety invariants WARP🔹CMD's checklist requires so a
future refactor cannot silently regress them:

  Group A — Per-user isolation of the dedup key. The risk gate's 30-min dedup
    lookup (``gate._idempotent_already_seen``) is keyed by the idempotency key
    string ALONE (``WHERE key=$1``). That is only safe because
    ``_build_idempotency_key`` folds ``user_id`` into the hash — otherwise two
    users trading the same market/side/day would collide and one would be
    silently deduped out. Proven here against the real function.

  Group B — User-owned risk can only TIGHTEN a safety gate, never disable it.
    ``gate._max_drawdown_breached`` honours ``min(8% system floor, user_pct)``:
    a user setting a LOOSER (>8%) threshold cannot prevent the 8% halt; a
    STRICTER setting halts earlier. Real function, fake pool.

  Group C — The loop cannot bypass consent / pause / kill switch. The real
    ``gate.evaluate`` rejects at the earliest gate for: auto_trade_on=False
    (no opt-in), paused=True, and kill-switch active. All three short-circuit
    at step <= 2, so the test is fully hermetic.

All hermetic — no DB, no broker, no network.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import projects.polymarket.crusaderbot.config as cfg
from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.gate import GateContext, GateResult
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj

_UID_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_UID_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


# ===========================================================================
# Group A — per-user isolation of the idempotency / dedup key
# ===========================================================================


def test_idempotency_key_differs_across_users_same_market():
    """Two users, same market/side/day → DISTINCT keys (no cross-user dedup)."""
    key_a = ssj._build_idempotency_key(_UID_A, "mkt-1", "yes", None)
    key_b = ssj._build_idempotency_key(_UID_B, "mkt-1", "yes", None)
    assert key_a != key_b, (
        "idempotency key must embed user_id — identical keys would let one "
        "user's trade silently dedup out another user's trade at gate step 10"
    )


def test_idempotency_key_stable_for_same_user_market_side_day(monkeypatch):
    """Same (user, market, side, UTC day) → identical key — dedup must hold.

    ``datetime`` is frozen so two sequential calls can never straddle a UTC-day
    boundary and spuriously differ (Gemini review, PR #1615).
    """
    class _FrozenDatetime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 4, 12, 0, tzinfo=tz)

    monkeypatch.setattr(ssj, "datetime", _FrozenDatetime)
    k1 = ssj._build_idempotency_key(_UID_A, "mkt-1", "yes", uuid4())
    k2 = ssj._build_idempotency_key(_UID_A, "mkt-1", "yes", uuid4())
    # publication_id is intentionally NOT in the hash (signature compat only),
    # so distinct pub ids for the same market/side/day still collapse to one key.
    assert k1 == k2


def test_idempotency_key_differs_by_side_and_market():
    base = ssj._build_idempotency_key(_UID_A, "mkt-1", "yes", None)
    assert base != ssj._build_idempotency_key(_UID_A, "mkt-1", "no", None)
    assert base != ssj._build_idempotency_key(_UID_A, "mkt-2", "yes", None)


def test_idempotency_key_has_namespaced_prefix():
    key = ssj._build_idempotency_key(_UID_A, "mkt-1", "yes", None)
    assert key.startswith("sf:")


# ===========================================================================
# Group B — user-owned drawdown threshold can only tighten the safety floor
# ===========================================================================


class _DrawdownConn:
    """Fake asyncpg conn for ``_max_drawdown_breached`` — returns fixed
    deposits for the ledger query and a fixed balance for the wallets query."""

    def __init__(self, deposits: Decimal, balance: Decimal) -> None:
        self._deposits = deposits
        self._balance = balance

    async def fetchval(self, sql: str, *args: Any) -> Any:
        low = sql.lower()
        if "ledger" in low:
            return self._deposits
        if "wallets" in low:
            return self._balance
        return Decimal("0")


def _patch_drawdown_pool(monkeypatch, deposits: Decimal, balance: Decimal) -> None:
    conn = _DrawdownConn(deposits, balance)
    acm = MagicMock()
    acm.__aenter__ = AsyncMock(return_value=conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = acm
    monkeypatch.setattr(gate_mod, "get_pool", lambda: pool)


def test_drawdown_default_floor_not_yet_breached(monkeypatch):
    # 7% actual drawdown, no user override → system 8% floor not yet hit.
    _patch_drawdown_pool(monkeypatch, Decimal("1000"), Decimal("930"))
    assert asyncio.run(gate_mod._max_drawdown_breached(_UID_A, None)) is False


def test_user_cannot_loosen_drawdown_floor(monkeypatch):
    """User sets 20% (>8% floor). A 10% drawdown MUST still halt at the 8% floor
    — the looser user value is ignored (cannot weaken a safety gate)."""
    _patch_drawdown_pool(monkeypatch, Decimal("1000"), Decimal("900"))  # 10% dd
    assert asyncio.run(gate_mod._max_drawdown_breached(_UID_A, 0.20)) is True


def test_user_loose_value_does_not_trip_below_floor(monkeypatch):
    """User sets 20% (>8%). A 7% drawdown is below the 8% floor → NOT breached
    (the loose value is clamped out; threshold stays the 8% floor)."""
    _patch_drawdown_pool(monkeypatch, Decimal("1000"), Decimal("930"))  # 7% dd
    assert asyncio.run(gate_mod._max_drawdown_breached(_UID_A, 0.20)) is False


def test_user_can_tighten_drawdown_earlier(monkeypatch):
    """User sets 5% (stricter). A 7% drawdown halts EARLY at the user value."""
    _patch_drawdown_pool(monkeypatch, Decimal("1000"), Decimal("930"))  # 7% dd
    assert asyncio.run(gate_mod._max_drawdown_breached(_UID_A, 0.05)) is True


# ===========================================================================
# Group C — the autonomous loop cannot bypass consent / pause / kill switch
# ===========================================================================


def _ctx(**overrides: Any) -> GateContext:
    base: dict[str, Any] = dict(
        user_id=_UID_A,
        telegram_user_id=9001,
        role="user",
        auto_trade_on=True,
        paused=False,
        market_id="mkt-1",
        side="yes",
        proposed_size_usdc=Decimal("10"),
        proposed_price=0.60,
        market_liquidity=50_000.0,
        market_status="active",
        edge_bps=None,
        signal_ts=datetime.now(timezone.utc),
        idempotency_key="sf:deadbeef",
        strategy_type="late_entry_v3",
        risk_profile="balanced",
        daily_loss_override=None,
        trading_mode="paper",
    )
    base.update(overrides)
    return GateContext(**base)


def _patch_gate_preamble(monkeypatch, *, kill_active: bool) -> None:
    """Stub everything before/at the consent + kill-switch gates so the real
    ``evaluate`` runs hermetically up to the first relevant short-circuit:
      - step 0 caps PASS (so we reach steps 1/2)
      - kill-switch controllable
      - risk_log writes are no-ops (no DB)
      - settings read is detached from .env
    """
    monkeypatch.setattr(gate_mod, "_log", AsyncMock())
    monkeypatch.setattr(
        gate_mod, "validate_risk_caps",
        AsyncMock(return_value=GateResult(True, "caps_ok")),
    )
    monkeypatch.setattr(
        gate_mod, "kill_switch_is_active", AsyncMock(return_value=kill_active),
    )
    monkeypatch.setattr(
        cfg, "get_settings",
        lambda: SimpleNamespace(MAX_OPEN_POSITIONS=5),
    )


def test_loop_rejected_when_user_not_opted_in(monkeypatch):
    """auto_trade_on=False (no opt-in) → reject at step 2. The autonomous loop
    can never trade for a user who has not explicitly opted in."""
    _patch_gate_preamble(monkeypatch, kill_active=False)
    res = asyncio.run(gate_mod.evaluate(_ctx(auto_trade_on=False)))
    assert res.approved is False
    assert res.failed_step == 2
    assert res.reason == "auto_trade_off_or_paused"


def test_loop_rejected_when_user_paused(monkeypatch):
    """paused=True is always honoured, even with auto_trade_on=True."""
    _patch_gate_preamble(monkeypatch, kill_active=False)
    res = asyncio.run(gate_mod.evaluate(_ctx(auto_trade_on=True, paused=True)))
    assert res.approved is False
    assert res.failed_step == 2


def test_loop_halted_by_kill_switch(monkeypatch):
    """Kill switch active → reject at step 1 before any sizing/execution,
    for a fully opted-in non-paused user."""
    _patch_gate_preamble(monkeypatch, kill_active=True)
    res = asyncio.run(gate_mod.evaluate(_ctx(auto_trade_on=True, paused=False)))
    assert res.approved is False
    assert res.failed_step == 1
    assert res.reason == "kill_switch_active"


def test_auto_trade_off_not_bypassable_without_explicit_per_task_optin(monkeypatch):
    """The auto_trade_on requirement is only skipped when a per-task opt-in flow
    explicitly sets bypass_auto_trade_check (e.g. an active copy-trade task).
    The autonomous signal path never sets it, so auto_trade_on=False blocks.
    This pins that the bypass is opt-in, not the default."""
    _patch_gate_preamble(monkeypatch, kill_active=False)
    # Default ctx (no bypass) with auto_trade_on=False is rejected at step 2 ...
    blocked = asyncio.run(gate_mod.evaluate(_ctx(auto_trade_on=False)))
    assert blocked.failed_step == 2
    # ... and the field defaults to False unless a per-task flow opts in.
    assert _ctx(auto_trade_on=False).bypass_auto_trade_check is False
