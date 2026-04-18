from __future__ import annotations

import json

import pytest

from projects.polymarket.polyquantbot.api.public_activation_trigger_cli import (
    _TRIGGER_RESULT_COMPLETED,
    _TRIGGER_RESULT_STOPPED_BLOCKED,
    _TRIGGER_RESULT_STOPPED_HOLD,
    _map_trigger_result,
    invoke_public_activation_cycle_trigger,
    main,
)
from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
    PublicActivationCyclePolicy,
    PublicActivationCycleResult,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
)


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


def test_trigger_surface_returns_completed_for_go_path() -> None:
    result = invoke_public_activation_cycle_trigger(_policy())
    assert result.trigger_result == _TRIGGER_RESULT_COMPLETED
    assert result.cycle_result_category == "completed"
    assert result.cycle_stop_reason is None


def test_trigger_surface_returns_stopped_hold_for_hold_path() -> None:
    result = invoke_public_activation_cycle_trigger(
        _policy(correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED)
    )
    assert result.trigger_result == _TRIGGER_RESULT_STOPPED_HOLD
    assert result.cycle_result_category == "stopped_hold"
    assert result.cycle_stop_reason == "readiness_hold"


def test_trigger_surface_returns_stopped_blocked_for_blocked_path() -> None:
    result = invoke_public_activation_cycle_trigger(
        _policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH)
    )
    assert result.trigger_result == _TRIGGER_RESULT_STOPPED_BLOCKED
    assert result.cycle_result_category == PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED
    assert result.cycle_stop_reason == "readiness_blocked"


def test_trigger_surface_policy_contract_requires_non_empty_identity_fields() -> None:
    with pytest.raises(ValueError, match="wallet_binding_id"):
        invoke_public_activation_cycle_trigger(_policy(wallet_binding_id=""))


def test_result_mapping_rejects_unknown_cycle_category() -> None:
    invalid_cycle_result = PublicActivationCycleResult(
        cycle_completed=False,
        cycle_result_category="unknown-category",
        cycle_stop_reason="bad",
        wallet_binding_id="wallet-1",
        owner_user_id="user-1",
        cycle_notes=[],
        readiness_result=None,  # type: ignore[arg-type]
        activation_gate_result=None,  # type: ignore[arg-type]
        activation_flow_result=None,  # type: ignore[arg-type]
        hardening_result=None,  # type: ignore[arg-type]
        execution_hook_result=None,  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="unsupported cycle_result_category"):
        _map_trigger_result(invalid_cycle_result)


def test_cli_main_emits_json_payload_for_trigger_result(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--wallet-binding-id",
            "wallet-1",
            "--owner-user-id",
            "user-1",
            "--requester-user-id",
            "user-1",
            "--wallet-active",
            "true",
            "--state-read-batch-ready",
            "true",
            "--reconciliation-outcome",
            WALLET_RECONCILIATION_OUTCOME_MATCH,
            "--correction-result-category",
            WALLET_CORRECTION_RESULT_ACCEPTED,
            "--retry-result-category",
            WALLET_RETRY_WORK_DECISION_SKIPPED,
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trigger_result"] == _TRIGGER_RESULT_COMPLETED
    assert payload["cycle_result_category"] == "completed"
    assert payload["cycle_stop_reason"] is None
