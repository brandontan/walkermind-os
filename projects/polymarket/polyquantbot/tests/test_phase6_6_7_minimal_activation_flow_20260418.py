from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    ACTIVATION_FLOW_RESULT_COMPLETED,
    ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
    ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
    ACTIVATION_FLOW_STOP_GATE_DENIED_BLOCKED,
    ACTIVATION_FLOW_STOP_GATE_DENIED_HOLD,
    ACTIVATION_FLOW_STOP_INVALID_CONTRACT,
    WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
    WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
    WALLET_PUBLIC_READINESS_RESULT_GO,
    WALLET_PUBLIC_READINESS_RESULT_HOLD,
    MinimalPublicActivationFlowBoundary,
    MinimalPublicActivationFlowPolicy,
    _validate_activation_flow_policy,
)


def _boundary() -> MinimalPublicActivationFlowBoundary:
    return MinimalPublicActivationFlowBoundary()


def _policy(**kwargs) -> MinimalPublicActivationFlowPolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requester_user_id": "user-1",
        "wallet_active": True,
        "readiness_result_category": WALLET_PUBLIC_READINESS_RESULT_GO,
        "readiness_notes": ["state_boundary_ready", "reconciliation_match", "retry_lane_clear"],
        "activation_result_category": WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
        "activation_notes": ["readiness_go_confirmed"],
    }
    defaults.update(kwargs)
    return MinimalPublicActivationFlowPolicy(**defaults)


# --- Validator ---


def test_validate_accepts_valid_allowed_policy() -> None:
    assert _validate_activation_flow_policy(_policy()) is None


def test_validate_accepts_valid_denied_hold_policy() -> None:
    assert _validate_activation_flow_policy(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            activation_notes=["readiness_hold_pending"],
        )
    ) is None


def test_validate_accepts_valid_denied_blocked_policy() -> None:
    assert _validate_activation_flow_policy(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            activation_notes=["readiness_blocked"],
        )
    ) is None


def test_validate_requires_wallet_binding_id() -> None:
    assert _validate_activation_flow_policy(_policy(wallet_binding_id=" ")) == "wallet_binding_id_required"


def test_validate_requires_owner_user_id() -> None:
    assert _validate_activation_flow_policy(_policy(owner_user_id="")) == "owner_user_id_required"


def test_validate_requires_requester_user_id() -> None:
    assert _validate_activation_flow_policy(_policy(requester_user_id="")) == "requester_user_id_required"


def test_validate_requires_bool_wallet_active() -> None:
    assert (
        _validate_activation_flow_policy(_policy(wallet_active="yes"))  # type: ignore[arg-type]
        == "wallet_active_must_be_bool"
    )


def test_validate_requires_known_readiness_result() -> None:
    assert (
        _validate_activation_flow_policy(_policy(readiness_result_category="unknown"))
        == "readiness_result_category_invalid"
    )


def test_validate_requires_readiness_notes_list() -> None:
    assert (
        _validate_activation_flow_policy(_policy(readiness_notes="not_a_list"))  # type: ignore[arg-type]
        == "readiness_notes_must_be_list"
    )


def test_validate_requires_known_activation_result() -> None:
    assert (
        _validate_activation_flow_policy(_policy(activation_result_category="unknown"))
        == "activation_result_category_invalid"
    )


def test_validate_requires_activation_notes_list() -> None:
    assert (
        _validate_activation_flow_policy(_policy(activation_notes="not_a_list"))  # type: ignore[arg-type]
        == "activation_notes_must_be_list"
    )


# --- Allowed path: flow completes ---


def test_flow_completes_when_gate_allowed() -> None:
    result = _boundary().run_activation_flow(_policy())
    assert result.flow_completed is True
    assert result.stop_reason is None
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_COMPLETED
    assert result.wallet_binding_id == "wallet-1"
    assert result.owner_user_id == "user-1"


def test_flow_completed_notes_include_activation_gate_allowed() -> None:
    result = _boundary().run_activation_flow(_policy())
    assert "activation_gate_allowed" in result.flow_notes


def test_flow_completed_notes_include_upstream_activation_notes() -> None:
    result = _boundary().run_activation_flow(_policy(activation_notes=["readiness_go_confirmed"]))
    assert "readiness_go_confirmed" in result.flow_notes


def test_flow_completed_notes_carries_readiness_and_activation_categories() -> None:
    result = _boundary().run_activation_flow(_policy())
    assert result.notes is not None
    assert result.notes["readiness_result_category"] == WALLET_PUBLIC_READINESS_RESULT_GO
    assert result.notes["activation_result_category"] == WALLET_ACTIVATION_GATE_RESULT_ALLOWED


# --- Hold path: flow stops with stopped_hold ---


def test_flow_stops_hold_when_gate_denied_hold() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            activation_notes=["readiness_hold_pending"],
        )
    )
    assert result.flow_completed is False
    assert result.stop_reason == ACTIVATION_FLOW_STOP_GATE_DENIED_HOLD
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_HOLD


def test_flow_stopped_hold_notes_include_gate_denied_hold_marker() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            activation_notes=["readiness_hold_pending"],
        )
    )
    assert "activation_gate_denied_hold" in result.flow_notes


def test_flow_stopped_hold_notes_include_upstream_activation_notes() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            activation_notes=["readiness_hold_pending"],
        )
    )
    assert "readiness_hold_pending" in result.flow_notes


def test_flow_stopped_hold_notes_dict() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            activation_notes=[],
        )
    )
    assert result.notes is not None
    assert result.notes["readiness_result_category"] == WALLET_PUBLIC_READINESS_RESULT_HOLD
    assert result.notes["activation_result_category"] == WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD


# --- Blocked path: flow stops with stopped_blocked ---


def test_flow_stops_blocked_when_gate_denied_blocked() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            activation_notes=["readiness_blocked"],
        )
    )
    assert result.flow_completed is False
    assert result.stop_reason == ACTIVATION_FLOW_STOP_GATE_DENIED_BLOCKED
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED


def test_flow_stopped_blocked_notes_include_gate_denied_blocked_marker() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            activation_notes=["readiness_blocked"],
        )
    )
    assert "activation_gate_denied_blocked" in result.flow_notes


def test_flow_stopped_blocked_notes_include_upstream_activation_notes() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            activation_notes=["readiness_blocked"],
        )
    )
    assert "readiness_blocked" in result.flow_notes


def test_flow_stopped_blocked_notes_dict() -> None:
    result = _boundary().run_activation_flow(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            activation_notes=[],
        )
    )
    assert result.notes is not None
    assert result.notes["readiness_result_category"] == WALLET_PUBLIC_READINESS_RESULT_BLOCKED
    assert result.notes["activation_result_category"] == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED


# --- Contract / ownership / wallet-active stop paths ---


def test_flow_stops_blocked_on_invalid_contract_missing_wallet_binding_id() -> None:
    result = _boundary().run_activation_flow(_policy(wallet_binding_id=""))
    assert result.flow_completed is False
    assert result.stop_reason == ACTIVATION_FLOW_STOP_INVALID_CONTRACT
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED


def test_flow_stops_blocked_on_invalid_readiness_category() -> None:
    result = _boundary().run_activation_flow(_policy(readiness_result_category="unknown"))
    assert result.flow_completed is False
    assert result.stop_reason == ACTIVATION_FLOW_STOP_INVALID_CONTRACT
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED


def test_flow_stops_blocked_on_invalid_activation_category() -> None:
    result = _boundary().run_activation_flow(_policy(activation_result_category="unknown"))
    assert result.flow_completed is False
    assert result.stop_reason == ACTIVATION_FLOW_STOP_INVALID_CONTRACT
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED


def test_flow_stops_blocked_on_owner_mismatch() -> None:
    result = _boundary().run_activation_flow(_policy(requester_user_id="other-user"))
    assert result.flow_completed is False
    assert result.stop_reason == ACTIVATION_FLOW_STOP_INVALID_CONTRACT
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED
    assert "owner_mismatch" in result.flow_notes


def test_flow_stops_blocked_on_inactive_wallet() -> None:
    result = _boundary().run_activation_flow(_policy(wallet_active=False))
    assert result.flow_completed is False
    assert result.stop_reason == ACTIVATION_FLOW_STOP_INVALID_CONTRACT
    assert result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED
    assert "wallet_not_active" in result.flow_notes


# --- Structural / identity ---


def test_flow_result_carries_wallet_binding_id_on_all_paths() -> None:
    for activation_cat, readiness_cat in [
        (WALLET_ACTIVATION_GATE_RESULT_ALLOWED, WALLET_PUBLIC_READINESS_RESULT_GO),
        (WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD, WALLET_PUBLIC_READINESS_RESULT_HOLD),
        (WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED, WALLET_PUBLIC_READINESS_RESULT_BLOCKED),
    ]:
        result = _boundary().run_activation_flow(
            _policy(
                readiness_result_category=readiness_cat,
                activation_result_category=activation_cat,
                activation_notes=[],
            )
        )
        assert result.wallet_binding_id == "wallet-1"
        assert result.owner_user_id == "user-1"


def test_flow_result_empty_notes_accepted() -> None:
    result = _boundary().run_activation_flow(
        _policy(readiness_notes=[], activation_notes=[])
    )
    assert result.flow_completed is True
    assert "activation_gate_allowed" in result.flow_notes
