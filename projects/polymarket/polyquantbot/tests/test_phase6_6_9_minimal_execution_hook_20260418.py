from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    ACTIVATION_FLOW_RESULT_COMPLETED,
    ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
    ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
    EXECUTION_HOOK_RESULT_EXECUTED,
    EXECUTION_HOOK_RESULT_STOPPED_BLOCKED,
    EXECUTION_HOOK_RESULT_STOPPED_HOLD,
    EXECUTION_HOOK_STOP_FLOW_NOT_COMPLETED,
    EXECUTION_HOOK_STOP_GATE_NOT_ALLOWED,
    EXECUTION_HOOK_STOP_HARDENING_BLOCKED,
    EXECUTION_HOOK_STOP_HARDENING_HOLD,
    EXECUTION_HOOK_STOP_INVALID_CONTRACT,
    MinimalExecutionHookBoundary,
    MinimalExecutionHookPolicy,
    PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
    PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD,
    PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
    WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
    _validate_execution_hook_policy,
)


def _boundary() -> MinimalExecutionHookBoundary:
    return MinimalExecutionHookBoundary()


def _policy(**kwargs) -> MinimalExecutionHookPolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requester_user_id": "user-1",
        "wallet_active": True,
        "hardening_outcome": PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
        "flow_result_category": ACTIVATION_FLOW_RESULT_COMPLETED,
        "activation_result_category": WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    }
    defaults.update(kwargs)
    return MinimalExecutionHookPolicy(**defaults)


# --- Validator ---


def test_validate_accepts_valid_pass_completed_allowed_policy() -> None:
    assert _validate_execution_hook_policy(_policy()) is None


def test_validate_accepts_valid_hold_stopped_hold_denied_hold_policy() -> None:
    assert _validate_execution_hook_policy(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
        )
    ) is None


def test_validate_accepts_valid_blocked_stopped_blocked_denied_blocked_policy() -> None:
    assert _validate_execution_hook_policy(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
        )
    ) is None


def test_validate_requires_wallet_binding_id() -> None:
    assert _validate_execution_hook_policy(_policy(wallet_binding_id="")) == "wallet_binding_id_required"
    assert _validate_execution_hook_policy(_policy(wallet_binding_id=" ")) == "wallet_binding_id_required"


def test_validate_requires_owner_user_id() -> None:
    assert _validate_execution_hook_policy(_policy(owner_user_id="")) == "owner_user_id_required"


def test_validate_requires_requester_user_id() -> None:
    assert _validate_execution_hook_policy(_policy(requester_user_id="")) == "requester_user_id_required"


def test_validate_requires_bool_wallet_active() -> None:
    assert (
        _validate_execution_hook_policy(_policy(wallet_active="yes"))  # type: ignore[arg-type]
        == "wallet_active_must_be_bool"
    )


def test_validate_requires_known_hardening_outcome() -> None:
    assert (
        _validate_execution_hook_policy(_policy(hardening_outcome="unknown"))
        == "hardening_outcome_invalid"
    )


def test_validate_requires_known_flow_result() -> None:
    assert (
        _validate_execution_hook_policy(_policy(flow_result_category="unknown"))
        == "flow_result_category_invalid"
    )


def test_validate_requires_known_gate_result() -> None:
    assert (
        _validate_execution_hook_policy(_policy(activation_result_category="unknown"))
        == "activation_result_category_invalid"
    )


# --- EXECUTED path ---


def test_hook_executed_on_pass_completed_allowed() -> None:
    result = _boundary().execute_hook(_policy())
    assert result.hook_executed is True
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_EXECUTED
    assert result.stop_reason is None


def test_hook_executed_notes_contain_all_three_pass_markers() -> None:
    result = _boundary().execute_hook(_policy())
    assert "hardening_pass" in result.execution_hook_notes
    assert "flow_completed" in result.execution_hook_notes
    assert "gate_allowed" in result.execution_hook_notes


def test_hook_executed_notes_dict_carries_all_categories() -> None:
    result = _boundary().execute_hook(_policy())
    assert result.notes is not None
    assert result.notes["hardening_outcome"] == PUBLIC_SAFETY_HARDENING_OUTCOME_PASS
    assert result.notes["flow_result_category"] == ACTIVATION_FLOW_RESULT_COMPLETED
    assert result.notes["activation_result_category"] == WALLET_ACTIVATION_GATE_RESULT_ALLOWED


def test_hook_executed_result_carries_identity_fields() -> None:
    result = _boundary().execute_hook(_policy())
    assert result.wallet_binding_id == "wallet-1"
    assert result.owner_user_id == "user-1"


# --- Contract / ownership / wallet-active stop paths ---


def test_hook_stopped_blocked_on_invalid_contract_empty_wallet_binding_id() -> None:
    result = _boundary().execute_hook(_policy(wallet_binding_id=""))
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
    assert result.stop_reason == EXECUTION_HOOK_STOP_INVALID_CONTRACT
    assert "contract_error" in result.execution_hook_notes


def test_hook_stopped_blocked_on_invalid_contract_unknown_hardening_outcome() -> None:
    result = _boundary().execute_hook(_policy(hardening_outcome="unknown"))
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
    assert result.stop_reason == EXECUTION_HOOK_STOP_INVALID_CONTRACT


def test_hook_stopped_blocked_on_owner_mismatch() -> None:
    result = _boundary().execute_hook(_policy(requester_user_id="other-user"))
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
    assert result.stop_reason == EXECUTION_HOOK_STOP_INVALID_CONTRACT
    assert "owner_mismatch" in result.execution_hook_notes


def test_hook_stopped_blocked_on_inactive_wallet() -> None:
    result = _boundary().execute_hook(_policy(wallet_active=False))
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
    assert result.stop_reason == EXECUTION_HOOK_STOP_INVALID_CONTRACT
    assert "wallet_not_active" in result.execution_hook_notes


# --- Hardening stop paths ---


def test_hook_stopped_blocked_on_hardening_blocked() -> None:
    result = _boundary().execute_hook(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
        )
    )
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
    assert result.stop_reason == EXECUTION_HOOK_STOP_HARDENING_BLOCKED
    assert "hardening_blocked" in result.execution_hook_notes


def test_hook_stopped_hold_on_hardening_hold() -> None:
    result = _boundary().execute_hook(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
        )
    )
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_HOLD
    assert result.stop_reason == EXECUTION_HOOK_STOP_HARDENING_HOLD
    assert "hardening_hold" in result.execution_hook_notes


def test_hook_hardening_blocked_stops_before_checking_flow_or_gate() -> None:
    result = _boundary().execute_hook(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
        )
    )
    assert result.stop_reason == EXECUTION_HOOK_STOP_HARDENING_BLOCKED
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED


# --- Flow stop paths (with hardening PASS) ---


def test_hook_stopped_blocked_on_flow_stopped_blocked() -> None:
    result = _boundary().execute_hook(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
        )
    )
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
    assert result.stop_reason == EXECUTION_HOOK_STOP_FLOW_NOT_COMPLETED
    assert "flow_stopped_blocked" in result.execution_hook_notes


def test_hook_stopped_hold_on_flow_stopped_hold() -> None:
    result = _boundary().execute_hook(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
        )
    )
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_HOLD
    assert result.stop_reason == EXECUTION_HOOK_STOP_FLOW_NOT_COMPLETED
    assert "flow_stopped_hold" in result.execution_hook_notes


# --- Gate stop paths (with hardening PASS, flow COMPLETED) ---


def test_hook_stopped_blocked_on_gate_denied_blocked() -> None:
    result = _boundary().execute_hook(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
        )
    )
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
    assert result.stop_reason == EXECUTION_HOOK_STOP_GATE_NOT_ALLOWED
    assert "gate_denied_blocked" in result.execution_hook_notes


def test_hook_stopped_hold_on_gate_denied_hold() -> None:
    result = _boundary().execute_hook(
        _policy(
            hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
        )
    )
    assert result.hook_executed is False
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_HOLD
    assert result.stop_reason == EXECUTION_HOOK_STOP_GATE_NOT_ALLOWED
    assert "gate_denied_hold" in result.execution_hook_notes


# --- Structural / result integrity ---


def test_hook_stop_reason_is_none_only_on_executed() -> None:
    result = _boundary().execute_hook(_policy())
    assert result.stop_reason is None
    assert result.hook_executed is True


def test_hook_executed_is_false_on_all_stop_paths() -> None:
    stop_policies = [
        _policy(wallet_binding_id=""),
        _policy(requester_user_id="other"),
        _policy(wallet_active=False),
        _policy(hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED),
        _policy(hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD),
        _policy(flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED),
        _policy(flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD),
        _policy(activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED),
        _policy(activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD),
    ]
    for pol in stop_policies:
        result = _boundary().execute_hook(pol)
        assert result.hook_executed is False, f"Expected hook_executed=False for policy: {pol}"


def test_hook_result_carries_wallet_binding_id_and_owner_on_all_outcomes() -> None:
    policies = [
        _policy(),
        _policy(hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED),
        _policy(hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD),
    ]
    for pol in policies:
        result = _boundary().execute_hook(pol)
        assert result.wallet_binding_id == "wallet-1"
        assert result.owner_user_id == "user-1"


def test_hook_stopped_blocked_result_category_never_has_none_stop_reason() -> None:
    result = _boundary().execute_hook(_policy(wallet_active=False))
    assert result.stop_reason is not None
    assert result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED
