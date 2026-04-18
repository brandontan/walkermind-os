from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PUBLIC_ACTIVATION_CYCLE_RESULT_COMPLETED,
    PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
    PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD,
    PUBLIC_ACTIVATION_CYCLE_STOP_INVALID_CONTRACT,
    PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_BLOCKED,
    PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_HOLD,
    PublicActivationCycleOrchestrationBoundary,
    PublicActivationCyclePolicy,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
    run_public_activation_cycle,
)


def _boundary() -> PublicActivationCycleOrchestrationBoundary:
    return PublicActivationCycleOrchestrationBoundary()


def _policy(**kwargs) -> PublicActivationCyclePolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requester_user_id": "user-1",
        "wallet_active": True,
        "state_read_batch_ready": True,
        "reconciliation_outcome": WALLET_RECONCILIATION_OUTCOME_MATCH,
        "correction_result_category": WALLET_CORRECTION_RESULT_ACCEPTED,
        "retry_result_category": WALLET_RETRY_WORK_DECISION_SKIPPED,
    }
    defaults.update(kwargs)
    return PublicActivationCyclePolicy(**defaults)


def test_cycle_entrypoint_returns_completed_for_go_path() -> None:
    result = run_public_activation_cycle(_policy())
    assert result.cycle_completed is True
    assert result.cycle_result_category == PUBLIC_ACTIVATION_CYCLE_RESULT_COMPLETED
    assert result.cycle_stop_reason is None
    assert "cycle_completed" in result.cycle_notes


def test_cycle_boundary_returns_stage_outputs_for_traceability() -> None:
    result = _boundary().run_public_activation_cycle(_policy())
    assert result.readiness_result.readiness_result_category == "go"
    assert result.activation_gate_result.activation_result_category == "allowed"
    assert result.activation_flow_result.flow_result_category == "completed"
    assert result.hardening_result.hardening_outcome == "pass"
    assert result.execution_hook_result.hook_result_category == "executed"


def test_cycle_stops_blocked_on_invalid_contract() -> None:
    result = _boundary().run_public_activation_cycle(_policy(wallet_binding_id=""))
    assert result.cycle_completed is False
    assert result.cycle_result_category == PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED
    assert result.cycle_stop_reason == PUBLIC_ACTIVATION_CYCLE_STOP_INVALID_CONTRACT
    assert result.readiness_result.blocked_reason == "invalid_contract"


def test_cycle_stops_hold_when_readiness_is_hold() -> None:
    result = _boundary().run_public_activation_cycle(
        _policy(correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED)
    )
    assert result.cycle_completed is False
    assert result.cycle_result_category == PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD
    assert result.cycle_stop_reason == PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_HOLD
    assert result.readiness_result.readiness_result_category == "hold"
    assert result.activation_gate_result.activation_result_category == "denied_hold"
    assert result.activation_flow_result.flow_result_category == "stopped_hold"


def test_cycle_stops_blocked_when_readiness_is_blocked() -> None:
    result = _boundary().run_public_activation_cycle(
        _policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH)
    )
    assert result.cycle_completed is False
    assert result.cycle_result_category == PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED
    assert result.cycle_stop_reason == PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_BLOCKED
    assert result.readiness_result.readiness_result_category == "blocked"
    assert result.activation_gate_result.activation_result_category == "denied_blocked"
    assert result.activation_flow_result.flow_result_category == "stopped_blocked"


def test_cycle_notes_include_deterministic_stage_markers() -> None:
    result = _boundary().run_public_activation_cycle(
        _policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH)
    )
    assert "readiness:blocked" in result.cycle_notes
    assert "activation_gate:denied_blocked" in result.cycle_notes
    assert "activation_flow:stopped_blocked" in result.cycle_notes
    assert "hardening:pass" in result.cycle_notes
    assert "execution_hook:stopped_blocked" in result.cycle_notes
