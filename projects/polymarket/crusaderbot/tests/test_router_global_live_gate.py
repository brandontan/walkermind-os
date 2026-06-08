"""WARP-92 — execution router global-live-gate enforcement.

The router must treat the global toggle as a hard AND before live execution:

  * global flag False → route to paper, write a live_blocked_fallback_paper
    audit event, and NEVER call assert_live_guards / the live engine.
  * global flag True → proceed exactly as before (assert_live_guards runs,
    live engine is invoked) — no regression.

Hermetic: every collaborator (global gate, audit, paper engine, live engine)
is patched. No DB, no network.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import router as router_mod

_UID = uuid4()


def _kwargs(chosen_mode="live"):
    return dict(
        chosen_mode=chosen_mode, user_id=_UID, telegram_user_id=123,
        role="admin", market_id="mkt-1", market_question="Q?",
        yes_token_id="tok-yes", no_token_id="tok-no",
        side="yes", size_usdc=Decimal("10"), price=0.5,
        idempotency_key="idem-1", strategy_type="signal",
        tp_pct=None, sl_pct=None, trading_mode="live",
        active_preset=None, strategy_metadata=None,
    )


def test_global_flag_false_routes_to_paper_and_audits():
    paper = AsyncMock(return_value={"mode": "paper"})
    audit_write = AsyncMock()
    assert_guards = patch.object(
        router_mod.live_engine, "assert_live_guards",
        side_effect=AssertionError("assert_live_guards must NOT be called"))
    with patch.object(router_mod, "is_global_live_enabled",
                      new=AsyncMock(return_value=False)), \
         patch.object(router_mod, "_paper", new=paper), \
         patch.object(router_mod.audit, "write", new=audit_write), \
         assert_guards:
        result = asyncio.run(router_mod.execute(**_kwargs()))

    assert result == {"mode": "paper"}
    paper.assert_awaited_once()
    # Audit fired with the global-disabled reason.
    audit_write.assert_awaited_once()
    _, kwargs = audit_write.await_args
    assert kwargs["action"] == "live_blocked_fallback_paper"
    assert kwargs["payload"]["reason"] == "global_live_trading_disabled"


def test_global_flag_true_proceeds_to_assert_guards():
    paper = AsyncMock(return_value={"mode": "paper"})
    live_exec = AsyncMock(return_value={"mode": "live"})
    guard_calls: list = []

    def _guard(role, trading_mode):
        guard_calls.append((role, trading_mode))

    with patch.object(router_mod, "is_global_live_enabled",
                      new=AsyncMock(return_value=True)), \
         patch.object(router_mod, "_paper", new=paper), \
         patch.object(router_mod.live_engine, "assert_live_guards",
                      side_effect=_guard), \
         patch.object(router_mod.live_engine, "execute", new=live_exec), \
         patch.object(router_mod.audit, "write", new=AsyncMock()):
        result = asyncio.run(router_mod.execute(**_kwargs()))

    # Global gate passed → guards asserted, live engine invoked, paper NOT used.
    assert guard_calls == [("admin", "live")]
    live_exec.assert_awaited_once()
    paper.assert_not_awaited()
    assert result == {"mode": "live"}


def test_paper_mode_skips_global_gate():
    paper = AsyncMock(return_value={"mode": "paper"})
    glg = AsyncMock(return_value=False)
    with patch.object(router_mod, "is_global_live_enabled", new=glg), \
         patch.object(router_mod, "_paper", new=paper):
        result = asyncio.run(router_mod.execute(**_kwargs(chosen_mode="paper")))
    assert result == {"mode": "paper"}
    # Paper path never consults the global live gate.
    glg.assert_not_awaited()
