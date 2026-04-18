from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    ACTIVATION_FLOW_RESULT_COMPLETED,
    ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
    ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_BLOCKED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_HOLD,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_COMPLETED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_HOLD,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_BLOCKED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_COMPLETED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_ALLOWED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_HOLD,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_BLOCKED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_HOLD,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_ALLOWED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_BLOCKED,
    PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
    PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD,
    PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
    PUBLIC_SAFETY_HARDENING_STOP_CROSS_BOUNDARY_INCONSISTENCY,
    PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH,
    PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT,
    PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH,
    PublicSafetyHardeningBoundary,
    PublicSafetyHardeningPolicy,
    WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
    WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
    WALLET_PUBLIC_READINESS_RESULT_GO,
    WALLET_PUBLIC_READINESS_RESULT_HOLD,
    _validate_hardening_policy,
)


def _boundary() -> PublicSafetyHardeningBoundary:
    return PublicSafetyHardeningBoundary()


def _policy(**kwargs) -> PublicSafetyHardeningPolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requester_user_id": "user-1",
        "wallet_active": True,
        "readiness_result_category": WALLET_PUBLIC_READINESS_RESULT_GO,
        "activation_result_category": WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
        "flow_result_category": ACTIVATION_FLOW_RESULT_COMPLETED,
    }
    defaults.update(kwargs)
    return PublicSafetyHardeningPolicy(**defaults)


# --- Validator ---


def test_validate_accepts_valid_go_allowed_completed_policy() -> None:
    assert _validate_hardening_policy(_policy()) is None


def test_validate_accepts_valid_hold_denied_hold_stopped_hold_policy() -> None:
    assert _validate_hardening_policy(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    ) is None


def test_validate_accepts_valid_blocked_denied_blocked_stopped_blocked_policy() -> None:
    assert _validate_hardening_policy(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
        )
    ) is None


def test_validate_requires_wallet_binding_id() -> None:
    assert _validate_hardening_policy(_policy(wallet_binding_id="")) == "wallet_binding_id_required"
    assert _validate_hardening_policy(_policy(wallet_binding_id=" ")) == "wallet_binding_id_required"


def test_validate_requires_owner_user_id() -> None:
    assert _validate_hardening_policy(_policy(owner_user_id="")) == "owner_user_id_required"


def test_validate_requires_requester_user_id() -> None:
    assert _validate_hardening_policy(_policy(requester_user_id="")) == "requester_user_id_required"


def test_validate_requires_bool_wallet_active() -> None:
    assert (
        _validate_hardening_policy(_policy(wallet_active="yes"))  # type: ignore[arg-type]
        == "wallet_active_must_be_bool"
    )


def test_validate_requires_known_readiness_result() -> None:
    assert (
        _validate_hardening_policy(_policy(readiness_result_category="unknown"))
        == "readiness_result_category_invalid"
    )


def test_validate_requires_known_gate_result() -> None:
    assert (
        _validate_hardening_policy(_policy(activation_result_category="unknown"))
        == "activation_result_category_invalid"
    )


def test_validate_requires_known_flow_result() -> None:
    assert (
        _validate_hardening_policy(_policy(flow_result_category="unknown"))
        == "flow_result_category_invalid"
    )


# --- PASS paths ---


def test_hardening_pass_go_allowed_completed() -> None:
    result = _boundary().check_hardening(_policy())
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_PASS
    assert result.stop_reason is None
    assert result.mismatch_block_reason is None


def test_hardening_pass_hold_denied_hold_stopped_hold() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_PASS
    assert result.stop_reason is None
    assert result.mismatch_block_reason is None


def test_hardening_pass_blocked_denied_blocked_stopped_blocked() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_PASS
    assert result.stop_reason is None
    assert result.mismatch_block_reason is None


def test_hardening_pass_notes_contain_consistency_markers() -> None:
    result = _boundary().check_hardening(_policy())
    assert "readiness_gate_consistent" in result.hardening_notes
    assert "gate_flow_consistent" in result.hardening_notes


# --- HOLD paths (recoverable mismatches) ---


def test_hardening_hold_readiness_go_gate_hold() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_HOLD


def test_hardening_hold_readiness_hold_gate_blocked() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_BLOCKED


def test_hardening_hold_gate_hold_flow_blocked() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_BLOCKED


def test_hardening_hold_notes_contain_mismatch_name() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    )
    assert PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_HOLD in result.hardening_notes


def test_hardening_hold_both_hold_mismatches_gives_cross_boundary_stop() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_CROSS_BOUNDARY_INCONSISTENCY
    assert PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_HOLD in result.hardening_notes
    assert PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_BLOCKED in result.hardening_notes


# --- BLOCKED paths (readiness->gate mismatch) ---


def test_hardening_blocked_readiness_go_gate_blocked() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_BLOCKED


def test_hardening_blocked_readiness_hold_gate_allowed() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_ALLOWED


def test_hardening_blocked_readiness_blocked_gate_allowed() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_ALLOWED


def test_hardening_blocked_readiness_blocked_gate_hold() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_HOLD


# --- BLOCKED paths (gate->flow mismatch) ---


def test_hardening_blocked_gate_allowed_flow_hold() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_HOLD


def test_hardening_blocked_gate_allowed_flow_blocked() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_BLOCKED


def test_hardening_blocked_gate_hold_flow_completed() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_COMPLETED


def test_hardening_blocked_gate_blocked_flow_completed() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_COMPLETED


def test_hardening_blocked_gate_blocked_flow_hold() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH
    assert result.mismatch_block_reason == PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_HOLD


# --- Contract / ownership / wallet-active gates ---


def test_hardening_blocked_on_invalid_contract_empty_wallet_binding_id() -> None:
    result = _boundary().check_hardening(_policy(wallet_binding_id=""))
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT
    assert result.mismatch_block_reason is None
    assert "contract_error" in result.hardening_notes


def test_hardening_blocked_on_invalid_contract_unknown_readiness() -> None:
    result = _boundary().check_hardening(_policy(readiness_result_category="unknown"))
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT


def test_hardening_blocked_on_invalid_contract_unknown_gate() -> None:
    result = _boundary().check_hardening(_policy(activation_result_category="unknown"))
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT


def test_hardening_blocked_on_invalid_contract_unknown_flow() -> None:
    result = _boundary().check_hardening(_policy(flow_result_category="unknown"))
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT


def test_hardening_blocked_on_owner_mismatch() -> None:
    result = _boundary().check_hardening(_policy(requester_user_id="other-user"))
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT
    assert result.mismatch_block_reason is None
    assert "owner_mismatch" in result.hardening_notes


def test_hardening_blocked_on_inactive_wallet() -> None:
    result = _boundary().check_hardening(_policy(wallet_active=False))
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT
    assert "wallet_not_active" in result.hardening_notes


# --- Structural / identity ---


def test_hardening_result_carries_wallet_binding_id_and_owner_user_id() -> None:
    for readiness, gate, flow in [
        (WALLET_PUBLIC_READINESS_RESULT_GO, WALLET_ACTIVATION_GATE_RESULT_ALLOWED, ACTIVATION_FLOW_RESULT_COMPLETED),
        (WALLET_PUBLIC_READINESS_RESULT_HOLD, WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD, ACTIVATION_FLOW_RESULT_STOPPED_HOLD),
        (WALLET_PUBLIC_READINESS_RESULT_BLOCKED, WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED, ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED),
    ]:
        result = _boundary().check_hardening(
            _policy(
                readiness_result_category=readiness,
                activation_result_category=gate,
                flow_result_category=flow,
            )
        )
        assert result.wallet_binding_id == "wallet-1"
        assert result.owner_user_id == "user-1"


def test_hardening_pass_notes_dict_carries_all_categories() -> None:
    result = _boundary().check_hardening(_policy())
    assert result.notes is not None
    assert result.notes["readiness_result_category"] == WALLET_PUBLIC_READINESS_RESULT_GO
    assert result.notes["activation_result_category"] == WALLET_ACTIVATION_GATE_RESULT_ALLOWED
    assert result.notes["flow_result_category"] == ACTIVATION_FLOW_RESULT_COMPLETED


def test_hardening_blocked_notes_dict_carries_mismatches_list() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
            flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
        )
    )
    assert result.notes is not None
    assert "mismatches" in result.notes
    assert PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_ALLOWED in result.notes["mismatches"]


def test_hardening_stop_reason_is_none_on_pass() -> None:
    result = _boundary().check_hardening(_policy())
    assert result.stop_reason is None


def test_hardening_mismatch_block_reason_is_none_on_pass() -> None:
    result = _boundary().check_hardening(_policy())
    assert result.mismatch_block_reason is None


def test_hardening_both_blocked_mismatches_gives_cross_boundary_stop_reason() -> None:
    result = _boundary().check_hardening(
        _policy(
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
        )
    )
    assert result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
    assert result.stop_reason == PUBLIC_SAFETY_HARDENING_STOP_CROSS_BOUNDARY_INCONSISTENCY
    assert PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_ALLOWED in result.hardening_notes
    assert PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_HOLD in result.hardening_notes
