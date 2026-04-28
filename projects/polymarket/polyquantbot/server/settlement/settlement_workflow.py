"""Settlement Workflow Engine — Priority 7 section 43.

Wraps FundSettlementEngine (synchronous, single-shot) with async lifecycle
management, status transitions, and idempotency enforcement.

P8-C hardening:
    settlement_policy_from_capital_config() derives SettlementWorkflowPolicy
    from CapitalModeConfig so real settlement cannot be enabled independently
    of the capital gate system.  allow_real_settlement is True only when all
    5 capital gates are on (is_capital_mode_allowed() == True).

Status transitions:
    PENDING -> PROCESSING -> COMPLETED
                          -> FAILED
                          -> BLOCKED
                          -> SIMULATED
    any -> CANCELLED (via cancel())
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Any

import structlog

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_STATUS_BLOCKED,
    FUND_SETTLEMENT_STATUS_COMPLETED,
    FUND_SETTLEMENT_STATUS_SIMULATED,
    FundSettlementEngine,
    FundSettlementExecutionInput,
    FundSettlementPolicyInput,
)

from .schemas import (
    SETTLEMENT_STATUS_BLOCKED,
    SETTLEMENT_STATUS_CANCELLED,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_FAILED,
    SETTLEMENT_STATUS_PROCESSING,
    SETTLEMENT_STATUS_SIMULATED,
    SettlementWorkflowRequest,
    SettlementWorkflowResult,
    _utc_now,
)

log = structlog.get_logger(__name__)


@dataclass
class SettlementWorkflowPolicy:
    """Runtime policy flags injected into the workflow engine.

    allow_real_settlement must be False unless ENABLE_LIVE_TRADING is set
    and all capital gates are on.  Use settlement_policy_from_capital_config()
    to derive this from CapitalModeConfig safely.
    """

    settlement_enabled: bool
    allow_real_settlement: bool
    simulation_mode: bool


def settlement_policy_from_capital_config(
    capital_config: "Any",  # CapitalModeConfig — forward ref avoids circular import
    settlement_enabled: bool = True,
) -> SettlementWorkflowPolicy:
    """Derive SettlementWorkflowPolicy from CapitalModeConfig.

    allow_real_settlement is True only when is_capital_mode_allowed() returns True
    (all 5 gates on, mode=LIVE).  This prevents settlement from being enabled
    independently of the capital gate system.

    Args:
        capital_config: CapitalModeConfig instance.
        settlement_enabled: Whether settlement processing is globally enabled.

    Returns:
        SettlementWorkflowPolicy with allow_real_settlement derived from gates.
    """
    allowed = capital_config.is_capital_mode_allowed()
    policy = SettlementWorkflowPolicy(
        settlement_enabled=settlement_enabled,
        allow_real_settlement=allowed,
        simulation_mode=not allowed,
    )
    log.info(
        "settlement_policy_derived_from_capital_config",
        allow_real_settlement=allowed,
        settlement_enabled=settlement_enabled,
        simulation_mode=policy.simulation_mode,
        capital_mode_allowed=allowed,
    )
    return policy


class SettlementWorkflowEngine:
    """Async, stateless coordinator that drives FundSettlementEngine through
    the settlement lifecycle.

    Receives all data pre-loaded from the service layer — never fetches DB
    records directly.  The settlement_id produced by FundSettlementEngine is
    the canonical idempotency key and is carried through unchanged.
    """

    def __init__(
        self,
        *,
        fund_engine: FundSettlementEngine,
        policy: SettlementWorkflowPolicy,
    ) -> None:
        self._fund_engine = fund_engine
        self._policy = policy

    async def execute(
        self,
        request: SettlementWorkflowRequest,
        execution_input: FundSettlementExecutionInput,
        policy_input: FundSettlementPolicyInput,
    ) -> SettlementWorkflowResult:
        """Execute one settlement attempt and return the workflow result."""
        bound = log.bind(
            workflow_id=request.workflow_id,
            correlation_id=request.correlation_id,
            wallet_id=request.wallet_id,
            mode=request.mode,
        )
        bound.info("settlement_workflow_execute_start")

        if not self._policy.settlement_enabled:
            bound.info("settlement_workflow_blocked_disabled")
            return SettlementWorkflowResult(
                workflow_id=request.workflow_id,
                status=SETTLEMENT_STATUS_BLOCKED,
                success=False,
                settlement_id=request.settlement_id,
                blocked_reason="settlement_disabled",
                trace_refs={"upstream": request.upstream_trace_refs},
            )

        if not self._policy.allow_real_settlement and request.mode == "live":
            bound.info("settlement_workflow_blocked_live_guard")
            return SettlementWorkflowResult(
                workflow_id=request.workflow_id,
                status=SETTLEMENT_STATUS_BLOCKED,
                success=False,
                settlement_id=request.settlement_id,
                blocked_reason="real_settlement_not_allowed",
                trace_refs={"upstream": request.upstream_trace_refs},
            )

        try:
            build_result = self._fund_engine.settle_with_trace(
                execution_input=execution_input,
                policy_input=policy_input,
            )
        except Exception as exc:
            bound.error("settlement_workflow_fund_engine_error", error=str(exc))
            return SettlementWorkflowResult(
                workflow_id=request.workflow_id,
                status=SETTLEMENT_STATUS_FAILED,
                success=False,
                settlement_id=request.settlement_id,
                blocked_reason=f"fund_engine_error: {exc}",
                trace_refs={"upstream": request.upstream_trace_refs},
            )

        fund_result = build_result.result
        trace = build_result.trace

        if fund_result is None:
            bound.warning("settlement_workflow_no_fund_result")
            return SettlementWorkflowResult(
                workflow_id=request.workflow_id,
                status=SETTLEMENT_STATUS_FAILED,
                success=False,
                settlement_id=request.settlement_id,
                blocked_reason="no_fund_result",
                trace_refs={"upstream": request.upstream_trace_refs},
            )

        status = _map_fund_status(fund_result.settlement_status)
        success = fund_result.success
        completed_at = _utc_now() if success else None

        bound.info(
            "settlement_workflow_execute_done",
            fund_status=fund_result.settlement_status,
            workflow_status=status,
            success=success,
        )

        return SettlementWorkflowResult(
            workflow_id=request.workflow_id,
            status=status,
            success=success,
            settlement_id=fund_result.settlement_id or request.settlement_id,
            blocked_reason=fund_result.blocked_reason,
            simulated=fund_result.simulated,
            fund_result=fund_result,
            trace_refs={
                "upstream": request.upstream_trace_refs,
                "fund_trace_blocked_reason": trace.blocked_reason,
                "fund_trace_notes": trace.settlement_notes,
            },
            completed_at=completed_at,
        )

    async def cancel(
        self,
        workflow_id: str,
        reason: str,
    ) -> SettlementWorkflowResult:
        """Cancel a workflow unconditionally.  Used by operator intervention."""
        log.info(
            "settlement_workflow_cancelled",
            workflow_id=workflow_id,
            reason=reason,
        )
        return SettlementWorkflowResult(
            workflow_id=workflow_id,
            status=SETTLEMENT_STATUS_CANCELLED,
            success=False,
            blocked_reason=reason,
            completed_at=_utc_now(),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _map_fund_status(fund_status: str) -> str:
    """Map FundSettlementEngine status to workflow status."""
    mapping: dict[str, str] = {
        FUND_SETTLEMENT_STATUS_COMPLETED: SETTLEMENT_STATUS_COMPLETED,
        FUND_SETTLEMENT_STATUS_BLOCKED:   SETTLEMENT_STATUS_BLOCKED,
        FUND_SETTLEMENT_STATUS_SIMULATED: SETTLEMENT_STATUS_SIMULATED,
    }
    return mapping.get(fund_status, SETTLEMENT_STATUS_FAILED)
