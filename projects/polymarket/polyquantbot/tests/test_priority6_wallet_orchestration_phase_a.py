"""Priority 6 — Multi-Wallet Orchestration Phase A — Tests.

Test IDs: WO-01 .. WO-12

Coverage:
  WO-01..WO-02  Domain model (WalletCandidate, RoutingRequest, OrchestrationResult)
  WO-03..WO-06  WalletSelectionPolicy filter chain
  WO-07..WO-08  WalletSelectionPolicy risk gate (hard) and ranking
  WO-09..WO-10  WalletOrchestrator async route() + error handling
  WO-11..WO-12  WalletSelectionPolicy strategy failover + exposure ceiling
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    OrchestrationResult,
    RoutingRequest,
    WalletCandidate,
    new_routing_id,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_orchestrator import (
    WalletOrchestrator,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_selector import (
    WalletSelectionPolicy,
)
from projects.polymarket.polyquantbot.server.schemas.portfolio import (
    MAX_DRAWDOWN,
    MAX_TOTAL_EXPOSURE_PCT,
)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _candidate(
    wallet_id: str = "wlc_aaa",
    tenant_id: str = "t1",
    user_id: str = "u1",
    lifecycle_status: str = "active",
    balance_usd: float = 1000.0,
    exposure_pct: float = 0.0,
    drawdown_pct: float = 0.0,
    strategy_tags: frozenset[str] = frozenset(),
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
        strategy_tags=strategy_tags,
        is_primary=is_primary,
    )


def _request(
    tenant_id: str = "t1",
    user_id: str = "u1",
    required_usd: float = 100.0,
    strategy_tag: str | None = None,
    mode: str = "paper",
) -> RoutingRequest:
    return RoutingRequest(
        tenant_id=tenant_id,
        user_id=user_id,
        required_usd=required_usd,
        strategy_tag=strategy_tag,
        mode=mode,
    )


_policy = WalletSelectionPolicy()


# ── WO-01: Domain model — WalletCandidate defaults ────────────────────────────

def test_wo_01_wallet_candidate_defaults():
    """WO-01: WalletCandidate constructs correctly with explicit fields and sane defaults."""
    c = _candidate()
    assert c.wallet_id == "wlc_aaa"
    assert c.lifecycle_status == "active"
    assert c.strategy_tags == frozenset()
    assert c.is_primary is True


# ── WO-02: Domain model — RoutingRequest auto correlation_id ─────────────────

def test_wo_02_routing_request_unique_correlation_ids():
    """WO-02: Two RoutingRequest objects get distinct auto-generated correlation IDs."""
    r1 = _request()
    r2 = _request()
    assert r1.correlation_id != r2.correlation_id
    assert r1.correlation_id.startswith("rtr_")


# ── WO-03: Policy — happy path routes to single active funded wallet ──────────

def test_wo_03_policy_routes_single_active_funded():
    """WO-03: Policy selects the only active+funded candidate."""
    result = _policy.select(_request(required_usd=100.0), [_candidate(balance_usd=500.0)])
    assert result.outcome == "routed"
    assert result.selected_wallet_id == "wlc_aaa"
    assert result.failover_used is False


# ── WO-04: Policy — no_active_wallet when all are deactivated ────────────────

def test_wo_04_policy_no_active_wallet():
    """WO-04: Policy returns no_active_wallet when all candidates are deactivated."""
    result = _policy.select(
        _request(),
        [_candidate(lifecycle_status="deactivated"), _candidate(wallet_id="wlc_bbb", lifecycle_status="blocked")],
    )
    assert result.outcome == "no_active_wallet"
    assert result.selected_wallet_id is None


# ── WO-05: Policy — insufficient_balance ─────────────────────────────────────

def test_wo_05_policy_insufficient_balance():
    """WO-05: Policy returns insufficient_balance when active wallet can't cover required_usd."""
    result = _policy.select(
        _request(required_usd=500.0),
        [_candidate(balance_usd=100.0)],
    )
    assert result.outcome == "insufficient_balance"
    assert result.selected_wallet_id is None


# ── WO-06: Policy — strategy-aware selection ─────────────────────────────────

def test_wo_06_policy_strategy_aware_selects_matching_wallet():
    """WO-06: Policy selects wallet whose strategy_tags include the requested tag
    over a wallet with no tag restrictions, when both are funded and active.
    Primary flag controls final tie-break — we give the matching wallet is_primary=True."""
    tagged = _candidate(
        wallet_id="wlc_tagged",
        strategy_tags=frozenset({"momentum"}),
        is_primary=True,
        balance_usd=800.0,
    )
    open_wallet = _candidate(
        wallet_id="wlc_open",
        strategy_tags=frozenset(),
        is_primary=False,
        balance_usd=900.0,
    )
    result = _policy.select(_request(strategy_tag="momentum"), [tagged, open_wallet])
    assert result.outcome == "routed"
    # Both pass strategy check (tagged explicitly, open_wallet by empty=all);
    # primary flag breaks the tie — tagged (is_primary=True) wins.
    assert result.selected_wallet_id == "wlc_tagged"
    assert result.failover_used is False


# ── WO-07: Policy — risk gate is hard; over-drawdown wallet is NOT routed ─────

def test_wo_07_policy_risk_blocked_not_routed():
    """WO-07: Wallet exceeding MAX_DRAWDOWN returns risk_blocked — risk gate is never bypassed."""
    over_drawdown = _candidate(
        wallet_id="wlc_risky",
        drawdown_pct=MAX_DRAWDOWN + 0.01,  # 0.09 — above ceiling
    )
    result = _policy.select(_request(), [over_drawdown])
    assert result.outcome == "risk_blocked"
    assert result.selected_wallet_id is None
    assert result.failover_used is False


# ── WO-08: Policy — primary ranked above secondary ───────────────────────────

def test_wo_08_policy_primary_ranked_first():
    """WO-08: When two wallets are eligible, the primary one wins regardless of balance."""
    primary = _candidate(wallet_id="wlc_primary", is_primary=True, balance_usd=200.0)
    secondary = _candidate(wallet_id="wlc_secondary", is_primary=False, balance_usd=900.0)
    result = _policy.select(_request(required_usd=100.0), [secondary, primary])
    assert result.outcome == "routed"
    assert result.selected_wallet_id == "wlc_primary"


# ── WO-09: Orchestrator — async route() returns policy result ────────────────

@pytest.mark.asyncio
async def test_wo_09_orchestrator_async_route():
    """WO-09: WalletOrchestrator.route() is async and delegates to policy correctly."""
    orchestrator = WalletOrchestrator()
    result = await orchestrator.route(
        _request(required_usd=50.0),
        [_candidate(balance_usd=500.0)],
    )
    assert result.outcome == "routed"
    assert result.selected_wallet_id == "wlc_aaa"


# ── WO-10: Orchestrator — error path returns outcome="error" ─────────────────

@pytest.mark.asyncio
async def test_wo_10_orchestrator_handles_policy_exception():
    """WO-10: If policy raises an unexpected exception, orchestrator returns outcome=error."""
    broken_policy = MagicMock(spec=WalletSelectionPolicy)
    broken_policy.select.side_effect = RuntimeError("simulated policy crash")

    orchestrator = WalletOrchestrator(policy=broken_policy)
    result = await orchestrator.route(_request(), [_candidate()])

    assert result.outcome == "error"
    assert result.selected_wallet_id is None
    assert "simulated policy crash" in result.reason


# ── WO-11: Policy — strategy failover routes risk-safe wallet ────────────────

def test_wo_11_policy_strategy_failover_routes_risk_safe_wallet():
    """WO-11: When a funded+risk-safe wallet fails the strategy filter, strategy
    failover selects it with failover_used=True — risk gate is not relaxed."""
    wrong_strategy = _candidate(
        wallet_id="wlc_wrong_strategy",
        strategy_tags=frozenset({"arbitrage"}),  # does not include "momentum"
        drawdown_pct=0.0,
        exposure_pct=0.0,
        balance_usd=500.0,
    )
    result = _policy.select(_request(strategy_tag="momentum"), [wrong_strategy])
    assert result.outcome == "routed"
    assert result.selected_wallet_id == "wlc_wrong_strategy"
    assert result.failover_used is True


# ── WO-12: Policy — exposure at ceiling is NOT routed ────────────────────────

def test_wo_12_policy_exposure_at_ceiling_not_routed():
    """WO-12: Wallet at MAX_TOTAL_EXPOSURE_PCT (strict <) returns risk_blocked."""
    at_ceiling = _candidate(
        wallet_id="wlc_exposed",
        exposure_pct=MAX_TOTAL_EXPOSURE_PCT,  # 0.10 — equals ceiling, strict < → blocked
        drawdown_pct=0.0,
    )
    result = _policy.select(_request(), [at_ceiling])
    assert result.outcome == "risk_blocked"
    assert result.selected_wallet_id is None
    assert result.failover_used is False
