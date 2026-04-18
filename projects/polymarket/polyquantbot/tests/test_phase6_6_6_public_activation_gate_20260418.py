from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_ACTIVATION_GATE_BLOCK_INVALID_CONTRACT,
    WALLET_ACTIVATION_GATE_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_ACTIVATION_GATE_BLOCK_READINESS_BLOCKED,
    WALLET_ACTIVATION_GATE_BLOCK_READINESS_HOLD,
    WALLET_ACTIVATION_GATE_BLOCK_WALLET_NOT_ACTIVE,
    WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
    WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
    WALLET_PUBLIC_READINESS_RESULT_GO,
    WALLET_PUBLIC_READINESS_RESULT_HOLD,
    WalletPublicActivationGateBoundary,
    WalletPublicActivationGatePolicy,
    _validate_activation_gate_policy,
)


def _boundary() -> WalletPublicActivationGateBoundary:
    return WalletPublicActivationGateBoundary()


def _policy(**kwargs) -> WalletPublicActivationGatePolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requested_by_user_id": "user-1",
        "wallet_active": True,
        "readiness_result_category": WALLET_PUBLIC_READINESS_RESULT_GO,
        "readiness_notes": ["state_boundary_ready", "reconciliation_match", "retry_lane_clear"],
    }
    defaults.update(kwargs)
    return WalletPublicActivationGatePolicy(**defaults)


# --- Validator ---


def test_validate_activation_gate_policy_accepts_valid_go_policy() -> None:
    assert _validate_activation_gate_policy(_policy()) is None


def test_validate_activation_gate_policy_accepts_valid_hold_policy() -> None:
    assert _validate_activation_gate_policy(_policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD)) is None


def test_validate_activation_gate_policy_accepts_valid_blocked_policy() -> None:
    assert _validate_activation_gate_policy(_policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED)) is None


def test_validate_activation_gate_policy_requires_wallet_binding_id() -> None:
    assert _validate_activation_gate_policy(_policy(wallet_binding_id=" ")) == "wallet_binding_id_required"


def test_validate_activation_gate_policy_requires_owner_user_id() -> None:
    assert _validate_activation_gate_policy(_policy(owner_user_id="")) == "owner_user_id_required"


def test_validate_activation_gate_policy_requires_requested_by_user_id() -> None:
    assert _validate_activation_gate_policy(_policy(requested_by_user_id="")) == "requested_by_user_id_required"


def test_validate_activation_gate_policy_requires_bool_wallet_active() -> None:
    assert (
        _validate_activation_gate_policy(_policy(wallet_active="yes"))  # type: ignore[arg-type]
        == "wallet_active_must_be_bool"
    )


def test_validate_activation_gate_policy_requires_known_readiness_result() -> None:
    assert (
        _validate_activation_gate_policy(_policy(readiness_result_category="unknown"))
        == "readiness_result_category_invalid"
    )


def test_validate_activation_gate_policy_requires_readiness_notes_list() -> None:
    assert (
        _validate_activation_gate_policy(_policy(readiness_notes="not_a_list"))  # type: ignore[arg-type]
        == "readiness_notes_must_be_list"
    )


# --- Contract / identity gate blocks ---


def test_gate_blocks_invalid_contract_empty_wallet_binding_id() -> None:
    result = _boundary().evaluate_activation_gate(_policy(wallet_binding_id=""))
    assert result.success is False
    assert result.blocked_reason == WALLET_ACTIVATION_GATE_BLOCK_INVALID_CONTRACT
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED
    assert "contract_error" in result.activation_notes


def test_gate_blocks_ownership_mismatch() -> None:
    result = _boundary().evaluate_activation_gate(_policy(requested_by_user_id="other-user"))
    assert result.success is False
    assert result.blocked_reason == WALLET_ACTIVATION_GATE_BLOCK_OWNERSHIP_MISMATCH
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED
    assert "owner_mismatch" in result.activation_notes


def test_gate_blocks_wallet_not_active() -> None:
    result = _boundary().evaluate_activation_gate(_policy(wallet_active=False))
    assert result.success is False
    assert result.blocked_reason == WALLET_ACTIVATION_GATE_BLOCK_WALLET_NOT_ACTIVE
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED
    assert "wallet_not_active" in result.activation_notes


# --- Deterministic activation outcomes ---


def test_gate_allows_when_readiness_is_go() -> None:
    result = _boundary().evaluate_activation_gate(_policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO))
    assert result.success is True
    assert result.blocked_reason is None
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_ALLOWED
    assert "readiness_go_confirmed" in result.activation_notes


def test_gate_allows_and_forwards_readiness_notes() -> None:
    notes = ["state_boundary_ready", "reconciliation_match", "correction_not_required", "retry_lane_clear"]
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO, readiness_notes=notes)
    )
    assert result.success is True
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_ALLOWED
    for note in notes:
        assert note in result.activation_notes
    assert "readiness_go_confirmed" in result.activation_notes


def test_gate_denies_hold_when_readiness_is_hold() -> None:
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD)
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_ACTIVATION_GATE_BLOCK_READINESS_HOLD
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD
    assert "readiness_hold_pending" in result.activation_notes


def test_gate_denies_hold_and_forwards_readiness_notes() -> None:
    notes = ["state_boundary_ready", "reconciliation_match", "retry_budget_exhausted"]
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD, readiness_notes=notes)
    )
    assert result.success is False
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD
    for note in notes:
        assert note in result.activation_notes
    assert "readiness_hold_pending" in result.activation_notes


def test_gate_denies_blocked_when_readiness_is_blocked() -> None:
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED)
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_ACTIVATION_GATE_BLOCK_READINESS_BLOCKED
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED
    assert "readiness_blocked" in result.activation_notes


def test_gate_denies_blocked_and_forwards_readiness_notes() -> None:
    notes = ["reconciliation_unresolved"]
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED, readiness_notes=notes)
    )
    assert result.success is False
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED
    assert "reconciliation_unresolved" in result.activation_notes
    assert "readiness_blocked" in result.activation_notes


# --- Result fields completeness ---


def test_gate_result_always_carries_wallet_binding_id_and_owner() -> None:
    result = _boundary().evaluate_activation_gate(_policy())
    assert result.wallet_binding_id == "wallet-1"
    assert result.owner_user_id == "user-1"


def test_gate_result_notes_dict_present_on_allowed() -> None:
    result = _boundary().evaluate_activation_gate(_policy())
    assert result.notes is not None
    assert result.notes.get("readiness_result_category") == WALLET_PUBLIC_READINESS_RESULT_GO


def test_gate_result_notes_dict_present_on_denied_hold() -> None:
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD)
    )
    assert result.notes is not None
    assert result.notes.get("readiness_result_category") == WALLET_PUBLIC_READINESS_RESULT_HOLD


def test_gate_result_notes_dict_present_on_denied_blocked() -> None:
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED)
    )
    assert result.notes is not None
    assert result.notes.get("readiness_result_category") == WALLET_PUBLIC_READINESS_RESULT_BLOCKED


# --- Empty readiness_notes is accepted ---


def test_gate_accepts_empty_readiness_notes_list_on_go() -> None:
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO, readiness_notes=[])
    )
    assert result.success is True
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_ALLOWED
    assert "readiness_go_confirmed" in result.activation_notes


def test_gate_accepts_empty_readiness_notes_list_on_hold() -> None:
    result = _boundary().evaluate_activation_gate(
        _policy(readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD, readiness_notes=[])
    )
    assert result.success is False
    assert result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD
    assert "readiness_hold_pending" in result.activation_notes
