"""Priority 6 — Multi-Wallet Orchestration Phase B — Tests.

Test IDs: WO-13 .. WO-27

Coverage:
  WO-13..WO-18  CrossWalletStateAggregator (section 39)
  WO-19..WO-22  WalletControlsStore (section 40)
  WO-23..WO-26  WalletOrchestrator Phase B pre-hook (overlay integration)
  WO-27         Integration: aggregate → disable breached wallet → route to healthy wallet
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.polyquantbot.server.orchestration.cross_wallet_aggregator import (
    CrossWalletStateAggregator,
)
from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    RISK_STATE_AT_RISK,
    RISK_STATE_BREACHED,
    RISK_STATE_HEALTHY,
    PortfolioControlOverlay,
    RoutingRequest,
    WalletCandidate,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_controls import (
    WalletControlsStore,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_orchestrator import (
    WalletOrchestrator,
)
from projects.polymarket.polyquantbot.server.schemas.portfolio import (
    MAX_DRAWDOWN,
    MAX_TOTAL_EXPOSURE_PCT,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _candidate(
    wallet_id: str = "wlc_aaa",
    tenant_id: str = "t1",
    user_id: str = "u1",
    lifecycle_status: str = "active",
    balance_usd: float = 1000.0,
    exposure_pct: float = 0.0,
    drawdown_pct: float = 0.0,
    is_primary: bool = True,
) -> WalletCandidate:
    return WalletCandidate(
        wallet_id=wallet_id,
        tenant_id=tenant_id,
        user_id=user_id,
        lifecycle_status=lifecycle_status,
        balance_usd=balance_usd,
        exposure_pct=exposure_pct,
        drawdown_pct=drawdown_pct,
        is_primary=is_primary,
    )


def _request(
    required_usd: float = 100.0,
    tenant_id: str = "t1",
    user_id: str = "u1",
) -> RoutingRequest:
    return RoutingRequest(tenant_id=tenant_id, user_id=user_id, required_usd=required_usd)


_aggregator = CrossWalletStateAggregator()


# ── WO-13..WO-18: CrossWalletStateAggregator ─────────────────────────────────

def test_wo13_single_active_wallet_healthy():
    """WO-13: Single active wallet with zero drawdown → risk_state=healthy."""
    c = _candidate(wallet_id="wlc_1", drawdown_pct=0.0)
    state = asyncio.run(_aggregator.aggregate("t1", "u1", [c]))
    assert state.wallet_count == 1
    assert state.active_count == 1
    assert state.wallets[0].risk_state == RISK_STATE_HEALTHY
    assert not state.has_conflict


def test_wo14_two_wallets_weighted_exposure():
    """WO-14: Two wallets — total_exposure_pct is balance-weighted average."""
    c1 = _candidate(wallet_id="wlc_1", balance_usd=1000.0, exposure_pct=0.05)
    c2 = _candidate(wallet_id="wlc_2", balance_usd=1000.0, exposure_pct=0.03)
    state = asyncio.run(_aggregator.aggregate("t1", "u1", [c1, c2]))
    # weighted: (0.05 * 1000 + 0.03 * 1000) / 2000 = 0.04
    assert abs(state.total_exposure_pct - 0.04) < 1e-9


def test_wo15_drawdown_at_risk_threshold():
    """WO-15: drawdown > MAX_DRAWDOWN * 0.75 but <= MAX_DRAWDOWN → at_risk."""
    at_risk_drawdown = MAX_DRAWDOWN * 0.75 + 0.001   # just above threshold
    c = _candidate(drawdown_pct=at_risk_drawdown)
    state = asyncio.run(_aggregator.aggregate("t1", "u1", [c]))
    assert state.wallets[0].risk_state == RISK_STATE_AT_RISK


def test_wo16_drawdown_breached():
    """WO-16: drawdown > MAX_DRAWDOWN → breached."""
    c = _candidate(drawdown_pct=MAX_DRAWDOWN + 0.001)
    state = asyncio.run(_aggregator.aggregate("t1", "u1", [c]))
    assert state.wallets[0].risk_state == RISK_STATE_BREACHED


def test_wo17_total_exposure_conflict():
    """WO-17: total_exposure_pct >= MAX_TOTAL_EXPOSURE_PCT → has_conflict=True."""
    c1 = _candidate(wallet_id="wlc_1", balance_usd=1000.0, exposure_pct=0.06)
    c2 = _candidate(wallet_id="wlc_2", balance_usd=1000.0, exposure_pct=0.06)
    # weighted: (0.06 + 0.06) / 2 = 0.06 < 0.10 — need higher values
    c3 = _candidate(wallet_id="wlc_1", balance_usd=500.0, exposure_pct=0.10)
    c4 = _candidate(wallet_id="wlc_2", balance_usd=500.0, exposure_pct=0.10)
    state = asyncio.run(_aggregator.aggregate("t1", "u1", [c3, c4]))
    assert state.has_conflict
    assert len(state.conflict_reasons) > 0


def test_wo18_empty_candidates():
    """WO-18: Empty candidate list → CrossWalletState with zero wallets, no conflict."""
    state = asyncio.run(_aggregator.aggregate("t1", "u1", []))
    assert state.wallet_count == 0
    assert state.active_count == 0
    assert state.total_exposure_pct == 0.0
    assert not state.has_conflict
    assert state.wallets == ()


# ── WO-19..WO-22: WalletControlsStore ────────────────────────────────────────

def test_wo19_disable_excludes_wallet():
    """WO-19: Disabled wallet is excluded from get_enabled_wallet_ids."""
    store = WalletControlsStore()
    result = store.disable_wallet("wlc_1", reason="risk breach")
    assert result.success
    assert result.action == "disable"
    enabled = store.get_enabled_wallet_ids(["wlc_1", "wlc_2"])
    assert "wlc_1" not in enabled
    assert "wlc_2" in enabled


def test_wo20_enable_previously_disabled():
    """WO-20: Re-enabling a disabled wallet includes it again."""
    store = WalletControlsStore()
    store.disable_wallet("wlc_1")
    result = store.enable_wallet("wlc_1")
    assert result.success
    assert result.action == "enable"
    enabled = store.get_enabled_wallet_ids(["wlc_1"])
    assert "wlc_1" in enabled


def test_wo21_set_global_halt_builds_overlay():
    """WO-21: set_global_halt → build_overlay returns global_halt=True with empty enabled set."""
    store = WalletControlsStore()
    store.set_global_halt("emergency stop")
    c = _candidate(wallet_id="wlc_1")
    overlay = store.build_overlay("t1", "u1", [c])
    assert overlay.global_halt is True
    assert overlay.halt_reason == "emergency stop"
    assert len(overlay.enabled_wallet_ids) == 0


def test_wo22_clear_global_halt():
    """WO-22: clear_global_halt → build_overlay returns global_halt=False."""
    store = WalletControlsStore()
    store.set_global_halt("test halt")
    store.clear_global_halt()
    c = _candidate(wallet_id="wlc_1")
    overlay = store.build_overlay("t1", "u1", [c])
    assert overlay.global_halt is False
    assert overlay.halt_reason == ""
    assert "wlc_1" in overlay.enabled_wallet_ids


# ── WO-23..WO-26: WalletOrchestrator overlay pre-hook ─────────────────────────

def test_wo23_global_halt_returns_halted():
    """WO-23: overlay with global_halt=True → outcome='halted'."""
    orchestrator = WalletOrchestrator()
    overlay = PortfolioControlOverlay(
        tenant_id="t1", user_id="u1",
        global_halt=True, halt_reason="circuit breaker",
        enabled_wallet_ids=frozenset(),
    )
    c = _candidate()
    result = asyncio.run(orchestrator.route(_request(), [c], overlay=overlay))
    assert result.outcome == "halted"
    assert result.selected_wallet_id is None
    assert "circuit breaker" in result.reason


def test_wo24_disabled_wallet_not_selected():
    """WO-24: overlay disables wlc_1; wlc_2 is selected instead."""
    orchestrator = WalletOrchestrator()
    c1 = _candidate(wallet_id="wlc_1", is_primary=True)
    c2 = _candidate(wallet_id="wlc_2", is_primary=False)
    overlay = PortfolioControlOverlay(
        tenant_id="t1", user_id="u1",
        global_halt=False, halt_reason="",
        enabled_wallet_ids=frozenset(["wlc_2"]),
    )
    result = asyncio.run(orchestrator.route(_request(), [c1, c2], overlay=overlay))
    assert result.outcome == "routed"
    assert result.selected_wallet_id == "wlc_2"


def test_wo25_no_overlay_phase_a_unchanged():
    """WO-25: overlay=None → Phase A behavior unchanged, wallet selected normally."""
    orchestrator = WalletOrchestrator()
    c = _candidate()
    result = asyncio.run(orchestrator.route(_request(), [c], overlay=None))
    assert result.outcome == "routed"
    assert result.selected_wallet_id == "wlc_aaa"


def test_wo26_all_disabled_no_candidate():
    """WO-26: All candidates disabled via overlay → outcome='no_candidate'."""
    orchestrator = WalletOrchestrator()
    c = _candidate(wallet_id="wlc_1")
    overlay = PortfolioControlOverlay(
        tenant_id="t1", user_id="u1",
        global_halt=False, halt_reason="",
        enabled_wallet_ids=frozenset(),  # none enabled
    )
    result = asyncio.run(orchestrator.route(_request(), [c], overlay=overlay))
    assert result.outcome == "no_candidate"
    assert result.selected_wallet_id is None


# ── WO-27: Integration ────────────────────────────────────────────────────────

def test_wo27_integration_aggregate_disable_route():
    """WO-27: Aggregate detects breached wallet → operator disables it → route picks healthy wallet."""
    breached = _candidate(wallet_id="wlc_breach", drawdown_pct=MAX_DRAWDOWN + 0.01, is_primary=True)
    healthy = _candidate(wallet_id="wlc_ok", drawdown_pct=0.01, is_primary=False)

    # Step 1: aggregate
    state = asyncio.run(_aggregator.aggregate("t1", "u1", [breached, healthy]))
    breached_status = next(w for w in state.wallets if w.wallet_id == "wlc_breach")
    assert breached_status.risk_state == RISK_STATE_BREACHED

    # Step 2: operator disables breached wallet
    store = WalletControlsStore()
    store.disable_wallet(breached_status.wallet_id, reason="breached drawdown threshold")

    # Step 3: build overlay and route
    overlay = store.build_overlay("t1", "u1", [breached, healthy])
    assert "wlc_breach" not in overlay.enabled_wallet_ids

    orchestrator = WalletOrchestrator()
    result = asyncio.run(orchestrator.route(_request(), [breached, healthy], overlay=overlay))

    assert result.outcome == "routed"
    assert result.selected_wallet_id == "wlc_ok"
