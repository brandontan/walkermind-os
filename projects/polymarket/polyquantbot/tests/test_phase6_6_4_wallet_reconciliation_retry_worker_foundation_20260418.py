from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_CORRECTION_BLOCK_INVALID_SNAPSHOT,
    WALLET_CORRECTION_BLOCK_REVISION_CONFLICT,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_CORRECTION_RESULT_NOT_REQUIRED,
    WALLET_CORRECTION_RESULT_PATH_BLOCKED,
    WALLET_RETRY_WORK_BLOCK_INVALID_CONTRACT,
    WALLET_RETRY_WORK_BLOCK_NON_RETRYABLE_RESULT,
    WALLET_RETRY_WORK_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_RETRY_WORK_BLOCK_RETRY_BUDGET_EXHAUSTED,
    WALLET_RETRY_WORK_BLOCK_WALLET_NOT_ACTIVE,
    WALLET_RETRY_WORK_DECISION_ACCEPTED,
    WALLET_RETRY_WORK_DECISION_BLOCKED,
    WALLET_RETRY_WORK_DECISION_EXHAUSTED,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
    WALLET_RETRY_WORK_MAX_BUDGET,
    WALLET_RETRY_WORKER_ACTION_RETRY,
    WALLET_RETRY_WORKER_ACTION_SKIP,
    WalletReconciliationRetryWorkPolicy,
    WalletReconciliationRetryWorkerBoundary,
    _validate_retry_work_policy,
)


def _boundary() -> WalletReconciliationRetryWorkerBoundary:
    return WalletReconciliationRetryWorkerBoundary()


def _policy(**kwargs) -> WalletReconciliationRetryWorkPolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requested_by_user_id": "user-1",
        "wallet_active": True,
        "correction_result_category": WALLET_CORRECTION_RESULT_PATH_BLOCKED,
        "correction_blocked_reason": None,
        "retry_attempt": 1,
        "retry_budget": 3,
        "worker_action": WALLET_RETRY_WORKER_ACTION_RETRY,
    }
    defaults.update(kwargs)
    return WalletReconciliationRetryWorkPolicy(**defaults)


# --- Validator ---

def test_validate_retry_policy_accepts_valid_path_blocked_retry() -> None:
    assert _validate_retry_work_policy(_policy()) is None


def test_validate_retry_policy_requires_wallet_binding_id() -> None:
    assert _validate_retry_work_policy(_policy(wallet_binding_id="  ")) == "wallet_binding_id_required"


def test_validate_retry_policy_requires_valid_result_category() -> None:
    assert (
        _validate_retry_work_policy(_policy(correction_result_category="unknown"))
        == "correction_result_category_invalid"
    )


def test_validate_retry_policy_rejects_non_str_block_reason() -> None:
    assert (
        _validate_retry_work_policy(_policy(correction_blocked_reason=123))  # type: ignore[arg-type]
        == "correction_blocked_reason_must_be_str_or_none"
    )


def test_validate_retry_policy_rejects_non_positive_retry_attempt() -> None:
    assert _validate_retry_work_policy(_policy(retry_attempt=0)) == "retry_attempt_must_be_positive"


def test_validate_retry_policy_rejects_budget_above_max() -> None:
    assert (
        _validate_retry_work_policy(_policy(retry_budget=WALLET_RETRY_WORK_MAX_BUDGET + 1))
        == "retry_budget_exceeds_max"
    )


def test_validate_retry_policy_rejects_unknown_worker_action() -> None:
    assert _validate_retry_work_policy(_policy(worker_action="hold")) == "worker_action_invalid"


# --- Worker decisions ---

def test_worker_skip_returns_skipped_success() -> None:
    result = _boundary().decide_retry_work_item(_policy(worker_action=WALLET_RETRY_WORKER_ACTION_SKIP))
    assert result.success is True
    assert result.blocked_reason is None
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_SKIPPED
    assert result.accepted_for_retry is False
    assert result.next_retry_attempt is None


def test_worker_retry_accepts_path_blocked_result() -> None:
    result = _boundary().decide_retry_work_item(_policy())
    assert result.success is True
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_ACCEPTED
    assert result.accepted_for_retry is True
    assert result.retry_attempt == 1
    assert result.retry_budget == 3
    assert result.next_retry_attempt == 2


def test_worker_retry_accepts_revision_conflict_blocked_result() -> None:
    result = _boundary().decide_retry_work_item(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
            correction_blocked_reason=WALLET_CORRECTION_BLOCK_REVISION_CONFLICT,
        )
    )
    assert result.success is True
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_ACCEPTED
    assert result.blocked_reason is None


def test_worker_retry_blocks_non_retryable_block_reason() -> None:
    result = _boundary().decide_retry_work_item(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
            correction_blocked_reason=WALLET_CORRECTION_BLOCK_INVALID_SNAPSHOT,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RETRY_WORK_BLOCK_NON_RETRYABLE_RESULT
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_BLOCKED


def test_worker_retry_blocks_non_retryable_accepted_correction_result() -> None:
    result = _boundary().decide_retry_work_item(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_ACCEPTED,
            correction_blocked_reason=None,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RETRY_WORK_BLOCK_NON_RETRYABLE_RESULT
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_BLOCKED


def test_worker_retry_blocks_non_retryable_not_required_correction_result() -> None:
    result = _boundary().decide_retry_work_item(
        _policy(
            correction_result_category=WALLET_CORRECTION_RESULT_NOT_REQUIRED,
            correction_blocked_reason=None,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RETRY_WORK_BLOCK_NON_RETRYABLE_RESULT
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_BLOCKED


def test_worker_retry_attempt_above_budget_returns_exhausted() -> None:
    result = _boundary().decide_retry_work_item(_policy(retry_attempt=4, retry_budget=3))
    assert result.success is False
    assert result.blocked_reason == WALLET_RETRY_WORK_BLOCK_RETRY_BUDGET_EXHAUSTED
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_EXHAUSTED


def test_worker_retry_on_budget_edge_is_accepted_with_no_next_attempt() -> None:
    result = _boundary().decide_retry_work_item(_policy(retry_attempt=3, retry_budget=3))
    assert result.success is True
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_ACCEPTED
    assert result.next_retry_attempt is None


def test_worker_ownership_mismatch_returns_blocked() -> None:
    result = _boundary().decide_retry_work_item(_policy(requested_by_user_id="user-2"))
    assert result.success is False
    assert result.blocked_reason == WALLET_RETRY_WORK_BLOCK_OWNERSHIP_MISMATCH
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_BLOCKED


def test_worker_inactive_wallet_returns_blocked() -> None:
    result = _boundary().decide_retry_work_item(_policy(wallet_active=False))
    assert result.success is False
    assert result.blocked_reason == WALLET_RETRY_WORK_BLOCK_WALLET_NOT_ACTIVE
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_BLOCKED


def test_worker_invalid_contract_returns_blocked() -> None:
    result = _boundary().decide_retry_work_item(_policy(retry_budget=0))
    assert result.success is False
    assert result.blocked_reason == WALLET_RETRY_WORK_BLOCK_INVALID_CONTRACT
    assert result.retry_result_category == WALLET_RETRY_WORK_DECISION_BLOCKED


def test_worker_exhausted_notes_include_budget_and_attempt() -> None:
    result = _boundary().decide_retry_work_item(_policy(retry_attempt=8, retry_budget=2))
    assert result.notes is not None
    assert result.notes.get("retry_attempt") == 8
    assert result.notes.get("retry_budget") == 2


def test_worker_accepted_notes_include_remaining_budget() -> None:
    result = _boundary().decide_retry_work_item(_policy(retry_attempt=2, retry_budget=5))
    assert result.notes is not None
    assert result.notes.get("retry_budget_remaining") == 3
    assert result.notes.get("worker_action") == WALLET_RETRY_WORKER_ACTION_RETRY


def test_worker_skip_notes_include_worker_action() -> None:
    result = _boundary().decide_retry_work_item(_policy(worker_action=WALLET_RETRY_WORKER_ACTION_SKIP))
    assert result.notes is not None
    assert result.notes.get("worker_action") == WALLET_RETRY_WORKER_ACTION_SKIP
