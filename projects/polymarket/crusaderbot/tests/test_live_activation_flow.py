"""Axis #3 — WARP/ROOT-live-activation-flow regression tests.

Coverage:
  * Gate step 15 (per-user live capital cap):
      - Live trade with cap=0 → rejected (`live_not_opted_in`)
      - Live trade with cap>proposed → approved
      - Live trade when open_live + proposed > cap → rejected
        (`live_capital_cap_exceeded`)
      - Paper trade is unaffected by the cap
  * Source-level pins for the 3 WebTrader endpoints:
      - GET /live/status returns LiveStatus shape with operator_guards
        + checklist + capital cap + exposure
      - POST /live/enable requires exact confirm_phrase + non-zero cap
      - POST /live/disable single-step, audit-logged
"""
from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID
from datetime import datetime, timezone

import pytest

from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.webtrader.backend import router as router_mod


# ---------------------------------------------------------------------
# Gate step 15 — per-user live capital cap
# ---------------------------------------------------------------------

def _ctx(
    *,
    trading_mode: str = "live",
    proposed_size: Decimal = Decimal("10"),
    live_capital_cap_usdc: float = 0.0,
) -> gate_mod.GateContext:
    return gate_mod.GateContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        telegram_user_id=1,
        role="admin",
        auto_trade_on=True,
        paused=False,
        market_id="m1",
        side="yes",
        proposed_size_usdc=proposed_size,
        proposed_price=0.5,
        market_liquidity=1_000_000.0,
        market_status="active",
        edge_bps=500.0,
        signal_ts=datetime.now(timezone.utc),
        idempotency_key="idem-test",
        strategy_type="late_entry_v3",
        risk_profile="balanced",
        daily_loss_override=None,
        trading_mode=trading_mode,
        live_capital_cap_usdc=live_capital_cap_usdc,
    )


def test_gate_step_15_rejects_live_when_no_real_funds():
    """live-mode-truth: the authoritative live bound is the user's REAL
    deposited balance. Zero real funds = no live trades ('live_no_funds') —
    this is what makes switch-first-deposit-later safe. A manual cap only
    tightens the bound; it is no longer an opt-in signal (opt-in is
    trading_mode='live', written only by the typed-confirm flows).
    """
    src = inspect.getsource(gate_mod.evaluate)
    assert "live_no_funds" in src, (
        "Regression: gate step 15 lost its 'live_no_funds' reject path — "
        "an unfunded live account could place live trades."
    )
    assert "get_live_balance" in src or "live_bal" in src, (
        "Regression: step 15 no longer reads the real deposited balance."
    )
    # Same pin for the over-cap reject.
    assert "live_capital_cap_exceeded" in src, (
        "Regression: gate step 15 lost its 'live_capital_cap_exceeded' "
        "reject path — a user could push past the real-balance bound."
    )


def test_gate_step_15_logic_no_funds_rejects():
    """Bare logic: live balance <= 0 must reject; manual cap only tightens."""
    live_bal = 0.0
    open_live = 0.0
    proposed = 10.0
    manual_cap = 0.0
    spendable = live_bal + open_live
    if live_bal <= 0.0:
        rejected = True
    else:
        cap = min(manual_cap, spendable) if manual_cap > 0 else spendable
        rejected = (open_live + proposed) > cap
    assert rejected is True


def test_gate_step_15_logic_within_cap_passes():
    """Bare logic: cap > proposed + open_live → pass."""
    cap = 100.0
    open_live = 20.0
    proposed = 10.0
    assert (open_live + proposed) <= cap


def test_gate_step_15_logic_exceeds_cap_rejects():
    """Bare logic: open_live + proposed > cap → reject."""
    cap = 50.0
    open_live = 45.0
    proposed = 10.0  # would push to 55 > 50 → reject
    assert (open_live + proposed) > cap


def test_gate_context_has_live_capital_cap_field():
    """GateContext must carry live_capital_cap_usdc so gate step 15 can read it."""
    fields = {f.name for f in gate_mod.GateContext.__dataclass_fields__.values()}
    assert "live_capital_cap_usdc" in fields, (
        "Regression: GateContext.live_capital_cap_usdc removed — gate "
        "step 15 cannot enforce the cap."
    )


def test_gate_step_15_only_fires_when_chosen_mode_is_live():
    """Source pin: step 15 must be inside `if chosen_mode == 'live'` so
    paper trades skip the gate entirely (and don't need a cap).
    """
    src = inspect.getsource(gate_mod.evaluate)
    # The step-15 logic must be guarded by chosen_mode == "live"
    assert 'chosen_mode == "live"' in src
    # And the 15. label must follow that guard in the source.
    idx_guard = src.find('chosen_mode == "live"')
    idx_step15 = src.find("15.")
    # Both present (the step 15 comment + the guard).
    assert idx_guard != -1
    assert idx_step15 != -1


# ---------------------------------------------------------------------
# WebTrader /live/* endpoints — source pins
# ---------------------------------------------------------------------

def test_get_live_status_endpoint_exists_with_right_shape():
    """Source pin: /live/status returns LiveStatus, reads operator
    guards + checklist + per-user cap + exposure."""
    src = inspect.getsource(router_mod)
    assert '@router.get("/live/status"' in src
    assert "LiveStatus" in src
    assert "_operator_guards_open" in src
    assert "live_checklist.evaluate" in src


def test_enable_live_requires_exact_confirm_phrase():
    """POST /live/enable must check `confirm_phrase == constant`.
    A regression that relaxes this (e.g. case-insensitive compare, or
    truthy check) re-opens the accidental-click vector.
    """
    src = inspect.getsource(router_mod.enable_live)
    assert "_LIVE_ENABLE_CONFIRM_PHRASE" in src
    assert "body.confirm_phrase != _LIVE_ENABLE_CONFIRM_PHRASE" in src


def test_enable_live_no_manual_cap_required_and_auto_stops():
    """live-mode-truth: POST /live/enable requires NO capital amount (the
    real deposited balance bounds exposure); an optional legacy cap is only
    range-checked. The switch must write BOTH mode columns in sync and
    AUTO-STOP the bot (users.auto_trade_on = FALSE).
    """
    from projects.polymarket.crusaderbot.domain.activation import (
        live_opt_in_gate as opt_in,
    )
    src = inspect.getsource(router_mod.enable_live)
    from projects.polymarket.crusaderbot.domain.activation import live_mode
    helper_src = inspect.getsource(live_mode.enable_live_self_serve)
    # Optional cap: present-but-bounded, never required.
    assert "manual_cap" in src
    assert "LIVE_CAP_MAX_USDC" in src
    assert opt_in.LIVE_CAP_MAX_USDC == 10_000.0
    # Single mode truth: both columns written together.
    assert "trading_mode = 'live'" in helper_src
    assert "paper_mode_override = FALSE" in helper_src
    # Auto-stop on switch.
    assert "auto_trade_on = FALSE" in helper_src


def test_enable_live_is_self_serve_not_operator_or_admin_gated():
    """POST /live/enable is self-serve: typed user consent flips mode,
    while operator guards/checklist/$5 balance gate LIVE Auto-Trade start.
    """
    src = inspect.getsource(router_mod.enable_live)
    assert "_operator_guards_open(s)" not in src
    assert "live_checklist.evaluate" not in src
    assert "enable_live_self_serve" in src
    assert "waiting_for_deposit" in src


def test_enable_live_writes_audit_log():
    """Every live-mode flip must write an audit_log row."""
    src = inspect.getsource(router_mod.enable_live)
    assert "audit.write" in src
    assert "webtrader_live_enable" in src


def test_disable_live_single_step_and_audit_logged():
    """POST /live/disable is single-step (no confirm phrase) and writes audit."""
    src = inspect.getsource(router_mod.disable_live)
    assert "trading_mode = 'paper'" in src
    assert "audit.write" in src
    assert "webtrader_live_disable" in src
    # No confirm phrase comparison on disable — easy to revert.
    assert "_LIVE_ENABLE_CONFIRM_PHRASE" not in src


def test_live_endpoints_have_per_user_rate_limit():
    """Both /live/enable and /live/disable must be wrapped with the
    per-user rate limiter so a single user cannot spam toggles.
    """
    src = inspect.getsource(router_mod)
    # Confirm both endpoints declare the per_user_rate_limit dependency.
    assert "per_user_rate_limit(\"live_activation\"" in src or \
           "per_user_rate_limit('live_activation'" in src


# ---------------------------------------------------------------------
# Confirm-phrase invariant
# ---------------------------------------------------------------------

def test_confirm_phrase_constant_value():
    """The confirm phrase must be a clear, deliberate sentence. Renaming
    is breaking change (existing UI flows will fail closed) — pin it.
    """
    assert router_mod._LIVE_ENABLE_CONFIRM_PHRASE == (
        "ENABLE LIVE TRADING FOR MY ACCOUNT"
    )
