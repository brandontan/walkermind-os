"""WARP-89 (gate-hotpath-db-fix) — the per-candidate risk gate must do ZERO
asyncpg reads for capital_alloc_pct.

Background: ``gate._capital_alloc_pct`` did a ``pool.acquire()`` +
``SELECT capital_alloc_pct FROM user_settings`` on EVERY candidate inside the hot
``evaluate`` path. Under a saturated pool that per-candidate acquire wedged prod
on Jun-7. This lane preloads the authoritative CAP% once per user per tick into
``GateContext.capital_alloc_pct`` and has ``evaluate`` read it from the context.

These tests pin the contract so a future refactor cannot silently regress it:

  * test_evaluate_step8_uses_preloaded_capital_alloc_no_db — with a preloaded
    ``capital_alloc_pct`` the gate reaches step 8 (capital-deployment cap) and
    rejects on it WITHOUT ever calling ``pool.acquire()``. The pool is patched to
    raise on acquire, so any per-candidate DB hit fails the test.

  * test_evaluate_falls_back_to_db_loader_when_not_preloaded — when
    ``capital_alloc_pct`` is None (legacy construction site outside the hot loop)
    the one-shot DB loader ``load_user_capital_alloc`` IS invoked, preserving
    behaviour for callers that have not yet been migrated.

  * test_resolve_capital_alloc_pct_semantics — the pure resolver applies the exact
    profile-default fallback + 80% clamp the DB loader used to.

All hermetic — no real DB, no broker, no network.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import projects.polymarket.crusaderbot.config as cfg
from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.gate import (
    GateContext,
    GateResult,
    resolve_capital_alloc_pct,
)

_UID = uuid4()


class _ExplodingPool:
    """A pool whose ``acquire()`` fails the test the instant it is touched.

    Any asyncpg connection acquire in the per-candidate evaluate path is exactly
    the Jun-7 prod-wedge regression this lane removes, so reaching here is a hard
    failure rather than a swallowed error.
    """

    def acquire(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        raise AssertionError(
            "per-candidate gate eval acquired a DB connection — capital_alloc_pct "
            "must come from the preloaded GateContext, not a per-candidate SELECT"
        )


def _ctx(**overrides: Any) -> GateContext:
    base: dict[str, Any] = dict(
        user_id=_UID,
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


def _stub_db_helpers(monkeypatch, *, balance: Decimal, open_exp: Decimal) -> None:
    """Replace every DB-touching helper evaluate() calls BEFORE step 8 with pure
    in-memory stubs, so the only thing that could still hit the pool is the
    capital_alloc_pct read this lane removed."""
    monkeypatch.setattr(gate_mod, "_log", AsyncMock())
    monkeypatch.setattr(
        gate_mod, "validate_risk_caps",
        AsyncMock(return_value=GateResult(True, "caps_ok")),
    )
    monkeypatch.setattr(
        gate_mod, "kill_switch_is_active", AsyncMock(return_value=False),
    )
    monkeypatch.setattr(gate_mod, "daily_pnl", AsyncMock(return_value=Decimal("0")))
    monkeypatch.setattr(
        gate_mod, "_max_drawdown_breached", AsyncMock(return_value=False),
    )
    monkeypatch.setattr(gate_mod, "_open_position_count", AsyncMock(return_value=0))
    monkeypatch.setattr(gate_mod, "get_balance", AsyncMock(return_value=balance))
    monkeypatch.setattr(gate_mod, "_open_exposure", AsyncMock(return_value=open_exp))
    # evaluate() does `from ...config import get_settings` at call time.
    monkeypatch.setattr(
        cfg, "get_settings",
        lambda: SimpleNamespace(MAX_OPEN_POSITIONS=5, MAX_DAILY_LOSS_USD=2000.0),
    )
    # Any pool.acquire() in the candidate path now explodes.
    monkeypatch.setattr(gate_mod, "get_pool", lambda: _ExplodingPool())


def test_evaluate_step8_uses_preloaded_capital_alloc_no_db(monkeypatch):
    """Preloaded CAP% reaches step 8 and rejects on it with ZERO pool.acquire().

    equity = 100 (balance 50 + open 50). open_exp + proposed = 50 + 10 = 60.
    60/100 = 0.60 > preloaded cap 0.20 → step 8 rejects. The rejection proves the
    gate actually consumed the preloaded value, and the exploding pool proves it
    did so without a DB read.
    """
    _stub_db_helpers(monkeypatch, balance=Decimal("50"), open_exp=Decimal("50"))
    # Guard: the one-shot DB loader must NOT be called on the preloaded path.
    loader = AsyncMock(side_effect=AssertionError("DB loader called on preload path"))
    monkeypatch.setattr(gate_mod, "_capital_alloc_pct", loader)
    monkeypatch.setattr(gate_mod, "load_user_capital_alloc", loader)

    res = asyncio.run(gate_mod.evaluate(_ctx(capital_alloc_pct=0.20)))

    assert res.approved is False
    assert res.failed_step == 8
    assert res.reason == "capital_deployment_cap"
    loader.assert_not_awaited()


def test_evaluate_preloaded_capital_alloc_passes_step8_no_db(monkeypatch):
    """A generous preloaded cap PASSES step 8 (and the trade proceeds past it),
    still with ZERO pool.acquire(). 60/100 = 0.60 <= cap 0.80 → step 8 OK."""
    _stub_db_helpers(monkeypatch, balance=Decimal("50"), open_exp=Decimal("50"))
    loader = AsyncMock(side_effect=AssertionError("DB loader called on preload path"))
    monkeypatch.setattr(gate_mod, "_capital_alloc_pct", loader)
    monkeypatch.setattr(gate_mod, "load_user_capital_alloc", loader)
    # Short-circuit the gate immediately AFTER step 8 so we don't have to stub the
    # remaining (signal-staleness/dedup/liquidity/edge) gates: a stale signal_ts
    # rejects at step 9, proving step 8 was passed.
    res = asyncio.run(gate_mod.evaluate(_ctx(
        capital_alloc_pct=0.80,
        signal_ts=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )))

    assert res.approved is False
    assert res.failed_step == 9  # passed step 8, rejected on staleness
    loader.assert_not_awaited()


def test_evaluate_falls_back_to_db_loader_when_not_preloaded(monkeypatch):
    """capital_alloc_pct=None (legacy site) → the one-shot DB loader is invoked.

    The loader is mocked (no real DB); we only assert the fallback contract: an
    unmigrated GateContext still resolves a CAP% via the single DB-read path.
    """
    _stub_db_helpers(monkeypatch, balance=Decimal("50"), open_exp=Decimal("50"))
    loader = AsyncMock(return_value=0.20)
    # The fallback calls the module-level patchable name (alias of the DB loader).
    monkeypatch.setattr(gate_mod, "_capital_alloc_pct", loader)

    res = asyncio.run(gate_mod.evaluate(_ctx(capital_alloc_pct=None)))

    loader.assert_awaited_once()
    assert res.failed_step == 8
    assert res.reason == "capital_deployment_cap"


def test_resolve_capital_alloc_pct_semantics():
    """Pure resolver: explicit value clamped to 80%; NULL/invalid → profile default."""
    assert resolve_capital_alloc_pct(0.60, "aggressive") == 0.60
    assert resolve_capital_alloc_pct(0.95, "aggressive") == 0.80  # clamp
    assert resolve_capital_alloc_pct(None, "balanced") == 0.40    # profile default
    assert resolve_capital_alloc_pct(0.0, "balanced") == 0.40     # non-positive → default
    assert resolve_capital_alloc_pct("bad", "balanced") == 0.40   # invalid → default
    assert resolve_capital_alloc_pct(None, "unknown_profile") == 0.40  # final fallback
