"""Priority 7 — Settlement Workflow Engine — Tests.

Test IDs: ST-01 .. ST-08

Coverage:
  ST-01  SettlementWorkflowRequest is a frozen dataclass
  ST-02  workflow_id auto-generated with "stl_" prefix
  ST-03  settlement_id is None by default on new request
  ST-04  Engine blocks when settlement_enabled=False
  ST-05  Engine blocks live mode when allow_real_settlement=False
  ST-06  Fund COMPLETED status maps to SETTLEMENT_STATUS_COMPLETED
  ST-07  settlement_id from fund_result is carried through unchanged
  ST-08  cancel() returns CANCELLED status with supplied reason
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_STATUS_BLOCKED,
    FUND_SETTLEMENT_STATUS_COMPLETED,
    FUND_SETTLEMENT_STATUS_SIMULATED,
    FundSettlementBuildResult,
    FundSettlementResult,
    FundSettlementTrace,
)
from projects.polymarket.polyquantbot.server.settlement.schemas import (
    SETTLEMENT_STATUS_BLOCKED,
    SETTLEMENT_STATUS_CANCELLED,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_SIMULATED,
    SettlementWorkflowRequest,
    SettlementWorkflowResult,
)
from projects.polymarket.polyquantbot.server.settlement.settlement_workflow import (
    SettlementWorkflowEngine,
    SettlementWorkflowPolicy,
    _map_fund_status,
)


# ── Stubs ─────────────────────────────────────────────────────────────────────

def _stub_fund_result(
    status: str = FUND_SETTLEMENT_STATUS_COMPLETED,
    settlement_id: str = "sha256abc",
    wallet_id: str = "wlc_001",
    amount: float = 100.0,
    currency: str = "USDC",
    success: bool = True,
    blocked_reason: str | None = None,
    simulated: bool = False,
) -> FundSettlementResult:
    return FundSettlementResult(
        settled=success,
        success=success,
        blocked_reason=blocked_reason,
        settlement_id=settlement_id,
        wallet_id=wallet_id,
        amount=amount,
        currency=currency,
        transfer_reference="ref_001",
        settlement_status=status,
        balance_before=500.0,
        balance_after=400.0,
        simulated=simulated,
        non_executing=False,
    )


def _stub_build_result(
    fund_result: FundSettlementResult | None = None,
    blocked_reason: str | None = None,
) -> FundSettlementBuildResult:
    if fund_result is None:
        fund_result = _stub_fund_result()
    return FundSettlementBuildResult(
        result=fund_result,
        trace=FundSettlementTrace(
            settlement_attempted=True,
            blocked_reason=blocked_reason,
        ),
    )


class StubFundEngine:
    """Configurable stub for FundSettlementEngine."""

    def __init__(self, *, build_result: FundSettlementBuildResult | None = None, raise_exc: Exception | None = None) -> None:
        self._build_result = build_result or _stub_build_result()
        self._raise_exc = raise_exc

    def settle_with_trace(self, *, execution_input, policy_input) -> FundSettlementBuildResult:
        if self._raise_exc:
            raise self._raise_exc
        return self._build_result


def _policy(
    settlement_enabled: bool = True,
    allow_real_settlement: bool = True,
    simulation_mode: bool = False,
) -> SettlementWorkflowPolicy:
    return SettlementWorkflowPolicy(
        settlement_enabled=settlement_enabled,
        allow_real_settlement=allow_real_settlement,
        simulation_mode=simulation_mode,
    )


def _request(mode: str = "paper", settlement_id: str | None = None) -> SettlementWorkflowRequest:
    return SettlementWorkflowRequest(
        wallet_id="wlc_001",
        amount=100.0,
        currency="USDC",
        method="polygon",
        mode=mode,
        settlement_id=settlement_id,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_st_01_request_is_frozen_dataclass():
    """ST-01: SettlementWorkflowRequest raises on mutation attempt."""
    req = _request()
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        req.wallet_id = "changed"  # type: ignore[misc]


def test_st_02_workflow_id_has_stl_prefix():
    """ST-02: Auto-generated workflow_id starts with 'stl_'."""
    req = _request()
    assert req.workflow_id.startswith("stl_")


def test_st_02b_workflow_ids_are_unique():
    """ST-02b: Two requests get distinct workflow_ids."""
    r1 = _request()
    r2 = _request()
    assert r1.workflow_id != r2.workflow_id


def test_st_03_settlement_id_defaults_none():
    """ST-03: settlement_id is None on a fresh request (before first fund engine call)."""
    req = _request()
    assert req.settlement_id is None


@pytest.mark.asyncio
async def test_st_04_engine_blocks_when_disabled():
    """ST-04: Engine returns BLOCKED when settlement_enabled=False."""
    engine = SettlementWorkflowEngine(
        fund_engine=StubFundEngine(),
        policy=_policy(settlement_enabled=False),
    )
    result = await engine.execute(_request(), object(), object())
    assert result.status == SETTLEMENT_STATUS_BLOCKED
    assert result.success is False
    assert result.blocked_reason == "settlement_disabled"


@pytest.mark.asyncio
async def test_st_05_engine_blocks_live_when_real_settlement_off():
    """ST-05: Engine returns BLOCKED for live mode when allow_real_settlement=False."""
    engine = SettlementWorkflowEngine(
        fund_engine=StubFundEngine(),
        policy=_policy(allow_real_settlement=False),
    )
    result = await engine.execute(_request(mode="live"), object(), object())
    assert result.status == SETTLEMENT_STATUS_BLOCKED
    assert result.blocked_reason == "real_settlement_not_allowed"


@pytest.mark.asyncio
async def test_st_06_completed_fund_status_maps_to_completed():
    """ST-06: Fund engine COMPLETED status produces SETTLEMENT_STATUS_COMPLETED."""
    fund_result = _stub_fund_result(status=FUND_SETTLEMENT_STATUS_COMPLETED, success=True)
    engine = SettlementWorkflowEngine(
        fund_engine=StubFundEngine(build_result=_stub_build_result(fund_result)),
        policy=_policy(),
    )
    result = await engine.execute(_request(), object(), object())
    assert result.status == SETTLEMENT_STATUS_COMPLETED
    assert result.success is True


@pytest.mark.asyncio
async def test_st_07_settlement_id_carried_from_fund_result():
    """ST-07: settlement_id from FundSettlementResult is returned unchanged."""
    expected_id = "sha256_canonical_key"
    fund_result = _stub_fund_result(settlement_id=expected_id)
    engine = SettlementWorkflowEngine(
        fund_engine=StubFundEngine(build_result=_stub_build_result(fund_result)),
        policy=_policy(),
    )
    result = await engine.execute(_request(), object(), object())
    assert result.settlement_id == expected_id


@pytest.mark.asyncio
async def test_st_08_cancel_returns_cancelled_status():
    """ST-08: cancel() always returns SETTLEMENT_STATUS_CANCELLED with the given reason."""
    engine = SettlementWorkflowEngine(
        fund_engine=StubFundEngine(),
        policy=_policy(),
    )
    result = await engine.cancel("stl_abc123", reason="operator_force_cancel")
    assert result.status == SETTLEMENT_STATUS_CANCELLED
    assert result.workflow_id == "stl_abc123"
    assert result.blocked_reason == "operator_force_cancel"
    assert result.success is False


# ── Status mapping unit tests ─────────────────────────────────────────────────

def test_st_06b_map_fund_status_blocked():
    """ST-06b: FUND BLOCKED maps to SETTLEMENT_STATUS_BLOCKED."""
    assert _map_fund_status(FUND_SETTLEMENT_STATUS_BLOCKED) == SETTLEMENT_STATUS_BLOCKED


def test_st_06c_map_fund_status_simulated():
    """ST-06c: FUND SIMULATED maps to SETTLEMENT_STATUS_SIMULATED."""
    assert _map_fund_status(FUND_SETTLEMENT_STATUS_SIMULATED) == SETTLEMENT_STATUS_SIMULATED


def test_st_06d_map_fund_status_unknown_falls_back_to_failed():
    """ST-06d: Unknown fund status falls back to FAILED."""
    from projects.polymarket.polyquantbot.server.settlement.schemas import SETTLEMENT_STATUS_FAILED
    assert _map_fund_status("UNKNOWN_STATUS") == SETTLEMENT_STATUS_FAILED
