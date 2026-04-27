"""Priority 6 — Multi-Wallet Orchestration Phase C — Tests.

Test IDs: WO-28 .. WO-45

Coverage:
  WO-28..WO-31  WalletControlsStore DB persistence (load/persist round-trip)
  WO-32..WO-35  OrchestrationDecisionStore (append/load_recent)
  WO-36..WO-39  OrchestratorService (route, aggregate, enable/disable/halt)
  WO-40..WO-43  Orchestration admin API routes (HTTP + auth guard)
  WO-44         degraded-mode outcome path in WalletOrchestrator
  WO-45         Backward-compatibility: overlay=None + no active candidates → no_candidate (not degraded)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.orchestration.cross_wallet_aggregator import (
    CrossWalletStateAggregator,
)
from projects.polymarket.polyquantbot.server.orchestration.decision_store import (
    OrchestrationDecisionStore,
)
from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    OrchestrationDecision,
    OrchestrationResult,
    RoutingRequest,
    WalletCandidate,
    decision_from_result,
    new_decision_id,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_controls import (
    WalletControlsStore,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_orchestrator import (
    WalletOrchestrator,
)
from projects.polymarket.polyquantbot.server.api.orchestration_routes import (
    build_orchestration_router,
)
from projects.polymarket.polyquantbot.server.services.orchestration_service import (
    OrchestratorService,
    RouteResult,
    _record_to_candidate,
)
from projects.polymarket.polyquantbot.server.schemas.portfolio import MAX_DRAWDOWN


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_candidate(
    wallet_id: str = "wlc_test",
    tenant_id: str = "t1",
    user_id: str = "u1",
    lifecycle_status: str = "active",
    balance_usd: float = 1000.0,
    exposure_pct: float = 0.02,
    drawdown_pct: float = 0.01,
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
        strategy_tags=frozenset(),
        is_primary=is_primary,
    )


def _make_request(
    tenant_id: str = "t1",
    user_id: str = "u1",
    required_usd: float = 100.0,
    mode: str = "paper",
) -> RoutingRequest:
    return RoutingRequest(
        tenant_id=tenant_id,
        user_id=user_id,
        required_usd=required_usd,
        mode=mode,
    )


def _make_db_mock(
    fetch_returns: list[dict[str, Any]] | None = None,
    execute_returns: bool = True,
) -> MagicMock:
    """Build a DatabaseClient mock with _fetch and _execute as coroutines."""
    db = MagicMock()
    db._fetch = AsyncMock(return_value=fetch_returns or [])
    db._execute = AsyncMock(return_value=execute_returns)
    return db


# ── WO-28: WalletControlsStore.load() restores disabled set from DB ──────────

@pytest.mark.asyncio
async def test_wo_28_controls_store_load_restores_disabled_set():
    """WO-28: load() populates _disabled from rows with is_disabled=True."""
    store = WalletControlsStore()
    db = _make_db_mock(fetch_returns=[
        {"wallet_id": "wlc_a", "is_disabled": True, "halt_reason": ""},
        {"wallet_id": "wlc_b", "is_disabled": True, "halt_reason": ""},
        {"wallet_id": "wlc_c", "is_disabled": False, "halt_reason": ""},
    ])
    await store.load(db, "t1", "u1")
    assert "wlc_a" in store._disabled
    assert "wlc_b" in store._disabled
    assert "wlc_c" not in store._disabled
    assert store._global_halt is False


# ── WO-29: WalletControlsStore.load() restores global halt from __global__ row

@pytest.mark.asyncio
async def test_wo_29_controls_store_load_restores_global_halt():
    """WO-29: load() sets _global_halt=True when __global__ row has is_disabled=True."""
    store = WalletControlsStore()
    db = _make_db_mock(fetch_returns=[
        {"wallet_id": "__global__", "is_disabled": True, "halt_reason": "emergency stop"},
    ])
    await store.load(db, "t1", "u1")
    assert store._global_halt is True
    assert store._halt_reason == "emergency stop"
    assert len(store._disabled) == 0  # __global__ is not a wallet_id


# ── WO-30: WalletControlsStore.persist() writes current state to DB ──────────

@pytest.mark.asyncio
async def test_wo_30_controls_store_persist_writes_state():
    """WO-30: persist() calls _execute for delete + global halt + each disabled wallet."""
    store = WalletControlsStore()
    store.disable_wallet("wlc_x")
    store.disable_wallet("wlc_y")
    store.set_global_halt("test halt")
    db = _make_db_mock(execute_returns=True)
    ok = await store.persist(db, "t1", "u1")
    assert ok is True
    # Expect: 1 DELETE + 1 global upsert + 2 wallet upserts = 4 calls
    assert db._execute.call_count == 4


# ── WO-31: WalletControlsStore.persist() fails gracefully on DB error ────────

@pytest.mark.asyncio
async def test_wo_31_controls_store_persist_fails_gracefully():
    """WO-31: persist() returns False when the DELETE _execute call fails."""
    store = WalletControlsStore()
    db = _make_db_mock(execute_returns=False)
    ok = await store.persist(db, "t1", "u1")
    assert ok is False


# ── WO-32: OrchestrationDecisionStore.append() writes decision to DB ─────────

@pytest.mark.asyncio
async def test_wo_32_decision_store_append():
    """WO-32: append() calls _execute with correct decision fields."""
    db = _make_db_mock(execute_returns=True)
    decision_store = OrchestrationDecisionStore(db=db)
    result = OrchestrationResult(
        outcome="routed",
        selected_wallet_id="wlc_z",
        reason="selected",
        candidates_evaluated=1,
    )
    decision = decision_from_result(result, tenant_id="t1", user_id="u1", mode="paper", correlation_id="corr_01")
    ok = await decision_store.append(decision)
    assert ok is True
    db._execute.assert_called_once()
    call_args = db._execute.call_args[0]
    assert "wlc_z" in call_args  # selected_wallet_id
    assert "routed" in call_args  # outcome


# ── WO-33: OrchestrationDecisionStore.append() is idempotent ─────────────────

@pytest.mark.asyncio
async def test_wo_33_decision_store_append_idempotent():
    """WO-33: append() uses ON CONFLICT DO NOTHING — duplicate call to DB is safe."""
    db = _make_db_mock(execute_returns=True)
    decision_store = OrchestrationDecisionStore(db=db)
    result = OrchestrationResult(
        outcome="halted", selected_wallet_id=None, reason="halt", candidates_evaluated=0,
    )
    decision = decision_from_result(result, "t1", "u1", "paper", "corr_02")
    await decision_store.append(decision)
    await decision_store.append(decision)  # second call — DB dedup handles it
    assert db._execute.call_count == 2  # both attempts reach DB; DB does dedup


# ── WO-34: OrchestrationDecisionStore.load_recent() returns rows ─────────────

@pytest.mark.asyncio
async def test_wo_34_decision_store_load_recent():
    """WO-34: load_recent() returns list of decision dicts in decided_at DESC order."""
    now = datetime.now(tz=timezone.utc)
    db = _make_db_mock(fetch_returns=[
        {"decision_id": "dec_01", "tenant_id": "t1", "user_id": "u1",
         "outcome": "routed", "selected_wallet_id": "wlc_a", "reason": "ok",
         "candidates_evaluated": 2, "failover_used": False, "mode": "paper",
         "correlation_id": "corr_01", "decided_at": now},
    ])
    decision_store = OrchestrationDecisionStore(db=db)
    rows = await decision_store.load_recent("t1", "u1", limit=10)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "routed"
    assert rows[0]["selected_wallet_id"] == "wlc_a"


# ── WO-35: OrchestrationDecisionStore.load_recent() returns [] on DB error ───

@pytest.mark.asyncio
async def test_wo_35_decision_store_load_recent_empty_on_error():
    """WO-35: load_recent() returns [] when _fetch returns empty (fail-safe)."""
    db = _make_db_mock(fetch_returns=[])
    decision_store = OrchestrationDecisionStore(db=db)
    rows = await decision_store.load_recent("t1", "u1")
    assert rows == []


# ── WO-36: OrchestratorService.route() returns RouteResult with decision ─────

@pytest.mark.asyncio
async def test_wo_36_orchestrator_service_route_success():
    """WO-36: route() produces RouteResult with outcome=routed and decision_persisted=True."""
    candidate = _make_candidate()
    lifecycle_store = MagicMock()
    lifecycle_store.list_wallets_for_user = AsyncMock(return_value=[])

    # Manually inject the candidate by patching _load_candidates
    controls_store = WalletControlsStore()
    db = _make_db_mock(execute_returns=True)
    decision_store = OrchestrationDecisionStore(db=db)
    aggregator = CrossWalletStateAggregator()
    orchestrator = WalletOrchestrator()

    svc = OrchestratorService(
        lifecycle_store=lifecycle_store,
        controls_store=controls_store,
        decision_store=decision_store,
        aggregator=aggregator,
        orchestrator=orchestrator,
        db=db,
    )

    # Patch _load_candidates to return one healthy candidate
    svc._load_candidates = AsyncMock(return_value=[candidate])

    request = _make_request()
    route_result = await svc.route(request)

    assert isinstance(route_result, RouteResult)
    assert route_result.result.outcome == "routed"
    assert route_result.result.selected_wallet_id == "wlc_test"
    assert route_result.decision_persisted is True


# ── WO-37: OrchestratorService.aggregate() returns CrossWalletState ──────────

@pytest.mark.asyncio
async def test_wo_37_orchestrator_service_aggregate():
    """WO-37: aggregate() returns a CrossWalletState with correct wallet count."""
    candidate = _make_candidate()
    db = _make_db_mock()
    svc = OrchestratorService(
        lifecycle_store=MagicMock(),
        controls_store=WalletControlsStore(),
        decision_store=OrchestrationDecisionStore(db=db),
        aggregator=CrossWalletStateAggregator(),
        orchestrator=WalletOrchestrator(),
        db=db,
    )
    svc._load_candidates = AsyncMock(return_value=[candidate])

    state = await svc.aggregate("t1", "u1")
    assert state.wallet_count == 1
    assert state.active_count == 1
    assert state.tenant_id == "t1"


# ── WO-38: OrchestratorService.enable/disable_wallet persists ────────────────

@pytest.mark.asyncio
async def test_wo_38_orchestrator_service_enable_disable_persists():
    """WO-38: enable_wallet and disable_wallet both call persist on the controls store."""
    db = _make_db_mock(execute_returns=True)
    controls_store = WalletControlsStore()
    svc = OrchestratorService(
        lifecycle_store=MagicMock(),
        controls_store=controls_store,
        decision_store=OrchestrationDecisionStore(db=db),
        aggregator=CrossWalletStateAggregator(),
        orchestrator=WalletOrchestrator(),
        db=db,
    )

    await svc.disable_wallet("t1", "u1", "wlc_test", reason="test")
    assert "wlc_test" in controls_store._disabled

    await svc.enable_wallet("t1", "u1", "wlc_test")
    assert "wlc_test" not in controls_store._disabled

    # persist was called twice (once for disable, once for enable)
    # Each persist does: DELETE + global upsert = at least 2 _execute calls
    assert db._execute.call_count >= 4


# ── WO-39: OrchestratorService.set_global_halt / clear_global_halt ───────────

@pytest.mark.asyncio
async def test_wo_39_orchestrator_service_halt_clear():
    """WO-39: set_global_halt and clear_global_halt update in-memory state and persist."""
    db = _make_db_mock(execute_returns=True)
    controls_store = WalletControlsStore()
    svc = OrchestratorService(
        lifecycle_store=MagicMock(),
        controls_store=controls_store,
        decision_store=OrchestrationDecisionStore(db=db),
        aggregator=CrossWalletStateAggregator(),
        orchestrator=WalletOrchestrator(),
        db=db,
    )

    await svc.set_global_halt("t1", "u1", reason="emergency")
    assert controls_store._global_halt is True
    assert controls_store._halt_reason == "emergency"

    await svc.clear_global_halt("t1", "u1")
    assert controls_store._global_halt is False
    assert controls_store._halt_reason == ""


# ── WO-40: API GET /admin/orchestration/wallets requires admin token ──────────

def _make_test_app(svc: Any = None) -> TestClient:
    app = FastAPI()
    app.include_router(build_orchestration_router())
    if svc is not None:
        app.state.orchestration_service = svc
    return TestClient(app, raise_server_exceptions=False)


def test_wo_40_admin_wallets_requires_token():
    """WO-40: GET /admin/orchestration/wallets returns 403 when token missing."""
    client = _make_test_app()
    resp = client.get("/admin/orchestration/wallets")
    assert resp.status_code == 403
    assert resp.json()["status"] == "forbidden"


# ── WO-41: API GET /admin/orchestration/wallets returns 503 when not wired ────

def test_wo_41_admin_wallets_503_when_service_not_wired():
    """WO-41: GET /admin/orchestration/wallets returns 503 when service not on app.state."""
    with patch.dict("os.environ", {"ORCHESTRATION_ADMIN_TOKEN": "test_token"}):
        client = _make_test_app(svc=None)
        resp = client.get(
            "/admin/orchestration/wallets",
            headers={"X-Orchestration-Admin-Token": "test_token"},
        )
    assert resp.status_code == 503


# ── WO-42: API POST /admin/orchestration/halt requires token ──────────────────

def test_wo_42_admin_halt_requires_token():
    """WO-42: POST /admin/orchestration/halt returns 403 when token missing."""
    client = _make_test_app()
    resp = client.post("/admin/orchestration/halt", json={"reason": "test"})
    assert resp.status_code == 403


# ── WO-43: API DELETE /admin/orchestration/halt requires token ───────────────

def test_wo_43_admin_clear_halt_requires_token():
    """WO-43: DELETE /admin/orchestration/halt returns 403 when token missing."""
    client = _make_test_app()
    resp = client.delete("/admin/orchestration/halt")
    assert resp.status_code == 403


# ── WO-44: WalletOrchestrator returns degraded when all active breach drawdown

@pytest.mark.asyncio
async def test_wo_44_orchestrator_degraded_outcome():
    """WO-44: outcome=degraded when all active candidates exceed MAX_DRAWDOWN."""
    orch = WalletOrchestrator()
    breached_drawdown = MAX_DRAWDOWN + 0.01  # just above ceiling

    candidates = [
        _make_candidate("wlc_a", drawdown_pct=breached_drawdown),
        _make_candidate("wlc_b", drawdown_pct=breached_drawdown),
    ]
    request = _make_request()
    result = await orch.route(request, candidates)
    assert result.outcome == "degraded"
    assert result.selected_wallet_id is None
    assert "drawdown ceiling" in result.reason


# ── WO-45: degraded does NOT fire when candidates list is empty or all inactive

@pytest.mark.asyncio
async def test_wo_45_degraded_not_fired_for_empty_or_inactive_candidates():
    """WO-45: degraded outcome not emitted when no active candidates exist."""
    orch = WalletOrchestrator()

    # Empty candidate list → no_candidate, not degraded
    result_empty = await orch.route(_make_request(), [])
    assert result_empty.outcome == "no_candidate"

    # Inactive candidates with high drawdown → no_active_wallet, not degraded
    inactive = [_make_candidate("wlc_x", lifecycle_status="blocked", drawdown_pct=0.50)]
    result_inactive = await orch.route(_make_request(), inactive)
    assert result_inactive.outcome == "no_active_wallet"
