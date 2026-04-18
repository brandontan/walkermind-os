from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_CORRECTION_RESULT_NOT_REQUIRED,
    WALLET_CORRECTION_RESULT_PATH_BLOCKED,
    WALLET_PUBLIC_READINESS_BLOCK_INVALID_CONTRACT,
    WALLET_PUBLIC_READINESS_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_PUBLIC_READINESS_BLOCK_RECONCILIATION_UNRESOLVED,
    WALLET_PUBLIC_READINESS_BLOCK_STATE_READ_NOT_READY,
    WALLET_PUBLIC_READINESS_BLOCK_WALLET_NOT_ACTIVE,
    WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
    WALLET_PUBLIC_READINESS_RESULT_GO,
    WALLET_PUBLIC_READINESS_RESULT_HOLD,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RETRY_WORK_DECISION_ACCEPTED,
    WALLET_RETRY_WORK_DECISION_BLOCKED,
    WALLET_RETRY_WORK_DECISION_EXHAUSTED,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
    WalletPublicReadinessBoundary,
    WalletPublicReadinessPolicy,
    _validate_public_readiness_policy,
)


def _boundary() -> WalletPublicReadinessBoundary:
    return WalletPublicReadinessBoundary()


def _policy(**kwargs) -> WalletPublicReadinessPolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requested_by_user_id": "user-1",
        "wallet_active": True,
        "state_read_batch_ready": True,
        "reconciliation_outcome": WALLET_RECONCILIATION_OUTCOME_MATCH,
        "correction_result_category": WALLET_CORRECTION_RESULT_NOT_REQUIRED,
        "retry_result_category": WALLET_RETRY_WORK_DECISION_SKIPPED,
    }
    defaults.update(kwargs)
    return WalletPublicReadinessPolicy(**defaults)


# --- Validator ---


def test_validate_public_readiness_policy_accepts_valid_policy() -> None:
    assert _validate_public_readiness_policy(_policy()) is None


def test_validate_public_readiness_policy_requires_wallet_binding_id() -> None:
    assert _validate_public_readiness_policy(_policy(wallet_binding_id=" ")) == "wallet_binding_id_required"


def test_validate_public_readiness_policy_requires_bool_state_ready() -> None:
    assert (
        _validate_public_readiness_policy(_policy(state_read_batch_ready="yes"))  # type: ignore[arg-type]
        == "state_read_batch_ready_must_be_bool"
    )


def test_validate_public_readiness_policy_requires_known_retry_result() -> None:
    assert _validate_public_readiness_policy(_policy(retry_result_category="unknown")) == "retry_result_category_invalid"


# --- Deterministic readiness outcomes ---


def test_readiness_returns_go_for_match_not_required_and_retry_skipped() -> None:
    result = _boundary().evaluate_public_readiness(_policy())
    assert result.success is True
    assert result.blocked_reason is None
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_GO
    assert "retry_lane_clear" in result.readiness_notes


def test_readiness_returns_go_for_match_correction_accepted_and_retry_skipped() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(correction_result_category=WALLET_CORRECTION_RESULT_ACCEPTED)
    )
    assert result.success is True
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_GO
    assert "correction_applied" in result.readiness_notes


def test_readiness_returns_hold_for_retry_accepted() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_ACCEPTED,
            retry_result_category=WALLET_RETRY_WORK_DECISION_ACCEPTED,
        )
    )
    assert result.success is True
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_HOLD
    assert "retry_resolution_pending" in result.readiness_notes


def test_readiness_returns_hold_for_retry_blocked() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_ACCEPTED,
            retry_result_category=WALLET_RETRY_WORK_DECISION_BLOCKED,
        )
    )
    assert result.success is True
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_HOLD


def test_readiness_returns_hold_for_retry_exhausted() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_ACCEPTED,
            retry_result_category=WALLET_RETRY_WORK_DECISION_EXHAUSTED,
        )
    )
    assert result.success is True
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_HOLD
    assert "retry_budget_exhausted" in result.readiness_notes


def test_readiness_returns_hold_for_correction_pending_path_blocked() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_PATH_BLOCKED,
            retry_result_category=WALLET_RETRY_WORK_DECISION_SKIPPED,
        )
    )
    assert result.success is True
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_HOLD
    assert "correction_resolution_pending" in result.readiness_notes


def test_readiness_returns_hold_for_correction_pending_blocked() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
            retry_result_category=WALLET_RETRY_WORK_DECISION_SKIPPED,
        )
    )
    assert result.success is True
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_HOLD


# --- Block contracts ---


def test_readiness_blocks_ownership_mismatch() -> None:
    result = _boundary().evaluate_public_readiness(_policy(requested_by_user_id="user-2"))
    assert result.success is False
    assert result.blocked_reason == WALLET_PUBLIC_READINESS_BLOCK_OWNERSHIP_MISMATCH
    assert result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_BLOCKED


def test_readiness_blocks_inactive_wallet() -> None:
    result = _boundary().evaluate_public_readiness(_policy(wallet_active=False))
    assert result.success is False
    assert result.blocked_reason == WALLET_PUBLIC_READINESS_BLOCK_WALLET_NOT_ACTIVE


def test_readiness_blocks_state_read_not_ready() -> None:
    result = _boundary().evaluate_public_readiness(_policy(state_read_batch_ready=False))
    assert result.success is False
    assert result.blocked_reason == WALLET_PUBLIC_READINESS_BLOCK_STATE_READ_NOT_READY


def test_readiness_blocks_reconciliation_unresolved() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH)
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_PUBLIC_READINESS_BLOCK_RECONCILIATION_UNRESOLVED


def test_readiness_blocks_invalid_contract() -> None:
    result = _boundary().evaluate_public_readiness(
        _policy(reconciliation_outcome="invalid")  # type: ignore[arg-type]
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_PUBLIC_READINESS_BLOCK_INVALID_CONTRACT
