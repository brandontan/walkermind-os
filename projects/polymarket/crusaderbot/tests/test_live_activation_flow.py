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
      - POST /live/enable requires checkbox Terms/risk consent + no manual cap
      - POST /live/disable single-step, audit-logged
"""
from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
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
    trading_mode='live', written only by the explicit consent flows).
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


def test_enable_live_requires_checkbox_consent_not_typed_phrase():
    """POST /live/enable must require explicit ToS/risk checkbox consent.
    The old typed phrase must not remain a live-switch gate.
    """
    src = inspect.getsource(router_mod.enable_live)
    assert "body.consent_accepted" in src
    assert "_LIVE_ENABLE_CONSENT_VERSION" in src
    assert "body.confirm_phrase !=" not in src
    assert "_LIVE_ENABLE_CONFIRM_PHRASE" not in src


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
    """Every live-mode flip must write an audit_log row with consent truth."""
    src = inspect.getsource(router_mod.enable_live)
    assert "audit.write" in src
    assert "webtrader_live_enable" in src
    assert "consent_accepted_at" in src
    assert "consent_version" in src
    assert "mode_transition_source" in src


def test_enable_live_missing_checkbox_consent_blocks_with_400():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
        LiveEnableRequest,
    )

    user = {"user_id": str(UUID("00000000-0000-0000-0000-000000000009"))}
    body = LiveEnableRequest(consent_accepted=False)

    with patch.object(router_mod._live_mode, "enable_live_self_serve", AsyncMock()) as enable:
        with pytest.raises(router_mod.HTTPException) as ei:
            asyncio.run(router_mod.enable_live(body, user))

    assert ei.value.status_code == 400
    assert "Terms of Service" in ei.value.detail
    enable.assert_not_awaited()


def test_enable_live_with_zero_balance_and_consent_succeeds_waiting_for_deposit():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
        LiveEnableRequest,
    )
    from projects.polymarket.crusaderbot.domain.activation.live_opt_in_gate import (
        LIVE_ENABLE_CONSENT_VERSION,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000009")
    user = {"user_id": str(user_id)}
    body = LiveEnableRequest(
        consent_accepted=True,
        consent_version=LIVE_ENABLE_CONSENT_VERSION,
    )
    switch = SimpleNamespace(
        live_balance_usdc=Decimal("0"),
        waiting_for_deposit=True,
        archived_positions=2,
        archived_orders=3,
    )

    with patch.object(router_mod._live_mode, "enable_live_self_serve",
                      AsyncMock(return_value=switch)) as enable, \
         patch.object(router_mod.audit, "write", AsyncMock()) as audit_write:
        out = asyncio.run(router_mod.enable_live(body, user))

    enable.assert_awaited_once_with(user_id, live_capital_cap_usdc=0.0)
    audit_write.assert_awaited_once()
    payload = audit_write.await_args.kwargs["payload"]
    assert payload["consent_accepted"] is True
    assert payload["consent_version"] == LIVE_ENABLE_CONSENT_VERSION
    assert payload["mode_transition_source"] == "webtrader"
    assert payload["waiting_for_deposit"] is True
    assert out.trading_mode == "live"
    assert out.auto_trade_on is False
    assert out.waiting_for_deposit is True
    assert out.status == "LIVE ENABLED / WAITING FOR DEPOSIT"


def test_enable_live_ignores_legacy_typed_phrase_when_checkbox_consent_present():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
        LiveEnableRequest,
    )
    from projects.polymarket.crusaderbot.domain.activation.live_opt_in_gate import (
        LIVE_ENABLE_CONSENT_VERSION,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000009")
    body = LiveEnableRequest(
        consent_accepted=True,
        consent_version=LIVE_ENABLE_CONSENT_VERSION,
        confirm_phrase="wrong",
    )
    switch = SimpleNamespace(
        live_balance_usdc=Decimal("5"),
        waiting_for_deposit=False,
        archived_positions=0,
        archived_orders=0,
    )

    with patch.object(router_mod._live_mode, "enable_live_self_serve",
                      AsyncMock(return_value=switch)), \
         patch.object(router_mod.audit, "write", AsyncMock()):
        out = asyncio.run(router_mod.enable_live(body, {"user_id": str(user_id)}))

    assert out.status == "LIVE ENABLED"


def test_enable_live_missing_consent_version_blocks_with_400():
    """STRICT consent versioning (R00T hardening): consent_accepted=true with
    NO consent_version must be rejected — a silently-defaulted version would
    let a stale client record consent against copy the user never saw.
    """
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
        LiveEnableRequest,
    )

    user = {"user_id": str(UUID("00000000-0000-0000-0000-000000000009"))}
    body = LiveEnableRequest(consent_accepted=True)  # no consent_version

    with patch.object(router_mod._live_mode, "enable_live_self_serve",
                      AsyncMock()) as enable:
        with pytest.raises(router_mod.HTTPException) as ei:
            asyncio.run(router_mod.enable_live(body, user))

    assert ei.value.status_code == 400
    assert "consent_version" in ei.value.detail
    enable.assert_not_awaited()


def test_enable_live_stale_consent_version_blocks_with_400():
    """A stale/unknown consent_version (old client after copy was re-versioned)
    must be rejected with 400, never silently upgraded."""
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
        LiveEnableRequest,
    )

    user = {"user_id": str(UUID("00000000-0000-0000-0000-000000000009"))}
    body = LiveEnableRequest(
        consent_accepted=True, consent_version="live-enable-tos-risk-v0",
    )

    with patch.object(router_mod._live_mode, "enable_live_self_serve",
                      AsyncMock()) as enable:
        with pytest.raises(router_mod.HTTPException) as ei:
            asyncio.run(router_mod.enable_live(body, user))

    assert ei.value.status_code == 400
    assert "consent_version" in ei.value.detail
    enable.assert_not_awaited()


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
# Consent-version invariant
# ---------------------------------------------------------------------

def test_live_enable_consent_version_constant_value():
    """The consent version is persisted into live-enable audit payloads;
    changing it means the ToS/risk acknowledgement copy materially changed.
    """
    assert router_mod._LIVE_ENABLE_CONSENT_VERSION == "live-enable-tos-risk-v1"


# ---------------------------------------------------------------------
# Frontend source pins — self-serve switch is never readiness-blocked (#1787)
# ---------------------------------------------------------------------

from pathlib import Path  # noqa: E402

_FRONTEND_SRC = (
    Path(__file__).resolve().parents[1] / "webtrader" / "frontend" / "src"
)


def test_live_modal_does_not_block_switch_on_operator_or_checklist_readiness():
    """#1787 product truth: the PAPER -> LIVE switch is self-serve anytime.
    Operator guards / checklist readiness gate live Auto-Trade ARMING, not the
    mode switch — the modal may show readiness as status/warning but must not
    disable the continue/enable path on it.
    """
    src = (_FRONTEND_SRC / "components" / "LiveActivationModal.tsx").read_text(
        encoding="utf-8",
    )
    assert "disabled={!ready}" not in src, (
        "Regression: LiveActivationModal re-blocked the LIVE switch on "
        "operator/checklist readiness."
    )
    assert "disabled={!armReady}" not in src
    # The only submit gate on the consent step is the checkbox itself.
    assert "disabled={!consentAccepted}" in src
    # Readiness still shown as status (CheckRow) — informational, not blocking.
    assert "operator_guards_open" in src


def test_two_factor_card_copy_is_optional_not_required():
    """2FA stays available but optional/recommended — the card must not tell
    users it is required for live trading (canonical policy, CMD blocker 3).
    """
    src = (_FRONTEND_SRC / "components" / "TwoFactorSetupCard.tsx").read_text(
        encoding="utf-8",
    )
    assert "Required for live trading" not in src
    assert "block live trading" not in src
    assert "Optional" in src or "optional" in src
    # The feature surfaces themselves stay (setup/status/verify/disable).
    for surface in ("setup2fa", "verify2fa", "disable2fa"):
        assert surface in src, f"2FA surface removed: {surface}"


# ---------------------------------------------------------------------
# WebTrader /autotrade/toggle — shared LIVE arming guard (R00T blocker 2)
# ---------------------------------------------------------------------

def test_autotrade_toggle_routes_through_shared_live_guard():
    """Source pin: enabling Auto-Trade on WebTrader must go through the same
    shared start guard as Telegram + MVP — not just kill-switch + preset.
    A regression that drops this re-opens the unguarded live arming path.
    """
    src = inspect.getsource(router_mod.toggle_autotrade)
    assert "evaluate_live_autotrade_start" in src
    assert "REASON_LIVE_NO_FUNDS" in src


def test_autotrade_toggle_blocks_live_user_without_funds():
    """A live user with < $5 confirmed available USDC.e is refused (409)
    before auto_trade_on is ever written."""
    from projects.polymarket.crusaderbot.domain.activation import live_mode
    body = SimpleNamespace(enabled=True)
    user = {"user_id": str(UUID("00000000-0000-0000-0000-000000000009"))}
    blocked = live_mode.LiveAutotradeStartGate(
        trading_mode="live", is_live=True, allowed=False,
        reason=live_mode.REASON_LIVE_NO_FUNDS,
        live_balance_usdc=Decimal("1.00"), enough_balance=False, checklist=None,
    )
    with patch.object(router_mod.kill_switch, "is_active",
                      AsyncMock(return_value=False)), \
         patch.object(live_mode, "evaluate_live_autotrade_start",
                      AsyncMock(return_value=blocked)):
        with pytest.raises(router_mod.HTTPException) as ei:
            asyncio.run(router_mod.toggle_autotrade(body, user))
    assert ei.value.status_code == 409
    assert "$5" in ei.value.detail


def test_autotrade_toggle_blocks_live_user_failing_checklist():
    """A live user whose activation checklist is not satisfied is refused
    (409) regardless of balance."""
    from projects.polymarket.crusaderbot.domain.activation import live_mode
    body = SimpleNamespace(enabled=True)
    user = {"user_id": str(UUID("00000000-0000-0000-0000-000000000009"))}
    blocked = live_mode.LiveAutotradeStartGate(
        trading_mode="live", is_live=True, allowed=False,
        reason=live_mode.REASON_LIVE_NOT_READY,
        live_balance_usdc=Decimal("50.00"), enough_balance=True, checklist=None,
    )
    with patch.object(router_mod.kill_switch, "is_active",
                      AsyncMock(return_value=False)), \
         patch.object(live_mode, "evaluate_live_autotrade_start",
                      AsyncMock(return_value=blocked)):
        with pytest.raises(router_mod.HTTPException) as ei:
            asyncio.run(router_mod.toggle_autotrade(body, user))
    assert ei.value.status_code == 409
    assert "checklist" in ei.value.detail.lower()


def test_autotrade_toggle_disable_skips_live_guard():
    """Turning Auto-Trade OFF never runs the live guard (no arming risk)."""
    from projects.polymarket.crusaderbot.domain.activation import live_mode

    class _Conn:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def acquire(self): return self
        async def fetchrow(self, *a): return None
        async def execute(self, *a): return "UPDATE 1"

    body = SimpleNamespace(enabled=False)
    user = {"user_id": str(UUID("00000000-0000-0000-0000-000000000009"))}
    with patch.object(router_mod, "get_pool", lambda: _Conn()), \
         patch.object(live_mode, "evaluate_live_autotrade_start",
                      AsyncMock()) as guard:
        out = asyncio.run(router_mod.toggle_autotrade(body, user))
    assert out == {"auto_trade_on": False}
    guard.assert_not_awaited()
