from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_CORRECTION_BLOCK_INVALID_CONTRACT,
    WALLET_CORRECTION_BLOCK_INVALID_SNAPSHOT,
    WALLET_CORRECTION_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_CORRECTION_BLOCK_PATH_REVISION_MISMATCH,
    WALLET_CORRECTION_BLOCK_PATH_STATE_MISSING,
    WALLET_CORRECTION_BLOCK_REVISION_CONFLICT,
    WALLET_CORRECTION_BLOCK_WALLET_NOT_ACTIVE,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_CORRECTION_RESULT_NOT_REQUIRED,
    WALLET_CORRECTION_RESULT_PATH_BLOCKED,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
    WalletCorrectionPolicy,
    WalletReconciliationCorrectionBoundary,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
    _validate_correction_policy,
)

_SNAPSHOT_READY = {"wallet_status": "ready", "available_balance": 100.0, "nonce": 1}
_SNAPSHOT_ALT = {"wallet_status": "suspended", "available_balance": 50.0, "nonce": 2}
_SNAPSHOT_INVALID = {"some_key": "missing_required_fields"}


def _make_storage_with(
    entries: list[tuple[str, str, dict]],
) -> WalletStateStorageBoundary:
    boundary = WalletStateStorageBoundary()
    for wallet_binding_id, owner_user_id, snapshot in entries:
        result = boundary.store_state(
            WalletStateStoragePolicy(
                wallet_binding_id=wallet_binding_id,
                owner_user_id=owner_user_id,
                wallet_active=True,
                state_snapshot=snapshot,
            )
        )
        assert result.success is True
    return boundary


def _make_correction(
    storage: WalletStateStorageBoundary | None = None,
) -> WalletReconciliationCorrectionBoundary:
    return WalletReconciliationCorrectionBoundary(storage or WalletStateStorageBoundary())


def _base_policy(**kwargs) -> WalletCorrectionPolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requested_by_user_id": "user-1",
        "wallet_active": True,
        "reconciliation_outcome": WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
        "correction_snapshot": _SNAPSHOT_ALT,
        "expected_stored_revision": 1,
    }
    defaults.update(kwargs)
    return WalletCorrectionPolicy(**defaults)


# --- Validator: contract field tests ---

def test_blank_wallet_binding_id_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(wallet_binding_id="")) == "wallet_binding_id_required"


def test_whitespace_wallet_binding_id_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(wallet_binding_id="   ")) == "wallet_binding_id_required"


def test_blank_owner_user_id_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(owner_user_id="")) == "owner_user_id_required"


def test_blank_requested_by_user_id_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(requested_by_user_id="")) == "requested_by_user_id_required"


def test_wallet_active_not_bool_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(wallet_active="yes")) == "wallet_active_must_be_bool"  # type: ignore[arg-type]


def test_invalid_reconciliation_outcome_string_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(reconciliation_outcome="unknown_outcome")) == "reconciliation_outcome_invalid"


def test_none_reconciliation_outcome_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(reconciliation_outcome=None)) == "reconciliation_outcome_invalid"  # type: ignore[arg-type]


def test_correction_snapshot_not_dict_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(correction_snapshot="not_a_dict")) == "correction_snapshot_must_be_dict"  # type: ignore[arg-type]


def test_expected_stored_revision_not_int_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(expected_stored_revision="1")) == "expected_stored_revision_must_be_int"  # type: ignore[arg-type]


def test_expected_stored_revision_bool_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(expected_stored_revision=True)) == "expected_stored_revision_must_be_int"  # type: ignore[arg-type]


def test_expected_stored_revision_zero_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(expected_stored_revision=0)) == "expected_stored_revision_must_be_positive"


def test_expected_stored_revision_negative_returns_invalid_contract() -> None:
    assert _validate_correction_policy(_base_policy(expected_stored_revision=-1)) == "expected_stored_revision_must_be_positive"


def test_valid_policy_validator_returns_none() -> None:
    assert _validate_correction_policy(_base_policy()) is None


def test_valid_policy_with_match_outcome_returns_none() -> None:
    assert _validate_correction_policy(_base_policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_MATCH)) is None


# --- Boundary: contract block ---

def test_blank_wallet_binding_id_boundary_returns_blocked() -> None:
    result = _make_correction().apply_correction(_base_policy(wallet_binding_id="  "))
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_INVALID_CONTRACT
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED
    assert result.applied_revision is None


def test_invalid_revision_boundary_returns_blocked() -> None:
    result = _make_correction().apply_correction(_base_policy(expected_stored_revision=0))
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_INVALID_CONTRACT
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED


# --- Boundary: ownership and active ---

def test_ownership_mismatch_returns_blocked() -> None:
    result = _make_correction().apply_correction(_base_policy(requested_by_user_id="user-2"))
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_OWNERSHIP_MISMATCH
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED
    assert result.applied_revision is None


def test_wallet_not_active_returns_blocked() -> None:
    result = _make_correction().apply_correction(_base_policy(wallet_active=False))
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_WALLET_NOT_ACTIVE
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED
    assert result.applied_revision is None


# --- Boundary: path decisions ---

def test_match_outcome_returns_not_required_success_true() -> None:
    result = _make_correction().apply_correction(
        _base_policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_MATCH)
    )
    assert result.success is True
    assert result.blocked_reason is None
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_NOT_REQUIRED
    assert result.applied_revision is None


def test_match_outcome_notes_contains_reconciliation_outcome() -> None:
    result = _make_correction().apply_correction(
        _base_policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_MATCH)
    )
    assert result.notes is not None
    assert result.notes.get("reconciliation_outcome") == WALLET_RECONCILIATION_OUTCOME_MATCH


def test_state_missing_outcome_returns_path_blocked() -> None:
    result = _make_correction().apply_correction(
        _base_policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_STATE_MISSING)
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_PATH_STATE_MISSING
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_PATH_BLOCKED
    assert result.applied_revision is None


def test_revision_mismatch_outcome_returns_path_blocked() -> None:
    result = _make_correction().apply_correction(
        _base_policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH)
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_PATH_REVISION_MISMATCH
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_PATH_BLOCKED
    assert result.applied_revision is None


def test_path_blocked_notes_contain_reconciliation_outcome() -> None:
    result = _make_correction().apply_correction(
        _base_policy(reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_STATE_MISSING)
    )
    assert result.notes is not None
    assert result.notes.get("reconciliation_outcome") == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING


# --- Boundary: snapshot_mismatch correction accepted ---

def test_snapshot_mismatch_with_matching_revision_returns_accepted() -> None:
    storage = _make_storage_with([("wallet-1", "user-1", _SNAPSHOT_READY)])
    result = _make_correction(storage).apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            correction_snapshot=_SNAPSHOT_ALT,
            expected_stored_revision=1,
        )
    )
    assert result.success is True
    assert result.blocked_reason is None
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_ACCEPTED
    assert result.applied_revision == 2


def test_applied_revision_increments_from_expected() -> None:
    storage = _make_storage_with([("wallet-1", "user-1", _SNAPSHOT_READY)])
    # advance to revision 2
    storage.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wallet-1",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot=_SNAPSHOT_READY,
        )
    )
    result = _make_correction(storage).apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            correction_snapshot=_SNAPSHOT_ALT,
            expected_stored_revision=2,
        )
    )
    assert result.success is True
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_ACCEPTED
    assert result.applied_revision == 3


def test_accepted_notes_contain_applied_revision_and_outcome() -> None:
    storage = _make_storage_with([("wallet-1", "user-1", _SNAPSHOT_READY)])
    result = _make_correction(storage).apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            correction_snapshot=_SNAPSHOT_ALT,
            expected_stored_revision=1,
        )
    )
    assert result.notes is not None
    assert result.notes.get("applied_revision") == 2
    assert result.notes.get("reconciliation_outcome") == WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH


# --- Boundary: revision_conflict cases ---

def test_state_not_in_storage_returns_revision_conflict() -> None:
    result = _make_correction().apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            expected_stored_revision=1,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_REVISION_CONFLICT
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED
    assert result.applied_revision is None


def test_stored_revision_mismatch_returns_revision_conflict() -> None:
    storage = _make_storage_with([("wallet-1", "user-1", _SNAPSHOT_READY)])
    result = _make_correction(storage).apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            expected_stored_revision=2,  # stored is 1
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_REVISION_CONFLICT
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED
    assert result.applied_revision is None


def test_revision_conflict_notes_contain_revision_mismatch_info() -> None:
    storage = _make_storage_with([("wallet-1", "user-1", _SNAPSHOT_READY)])
    result = _make_correction(storage).apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            expected_stored_revision=99,
        )
    )
    assert result.notes is not None
    assert result.notes.get("stored_revision") == 1
    assert result.notes.get("expected_stored_revision") == 99


# --- Boundary: invalid correction snapshot ---

def test_invalid_correction_snapshot_returns_snapshot_invalid() -> None:
    storage = _make_storage_with([("wallet-1", "user-1", _SNAPSHOT_READY)])
    result = _make_correction(storage).apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            correction_snapshot=_SNAPSHOT_INVALID,
            expected_stored_revision=1,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_INVALID_SNAPSHOT
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED
    assert result.applied_revision is None


def test_correction_snapshot_with_negative_balance_returns_snapshot_invalid() -> None:
    storage = _make_storage_with([("wallet-1", "user-1", _SNAPSHOT_READY)])
    bad_snapshot = {"wallet_status": "ready", "available_balance": -1.0, "nonce": 1}
    result = _make_correction(storage).apply_correction(
        _base_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            correction_snapshot=bad_snapshot,
            expected_stored_revision=1,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_INVALID_SNAPSHOT
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED


# --- Owner isolation ---

def test_owner_isolation_cross_owner_state_not_visible() -> None:
    storage = _make_storage_with([("wallet-1", "user-2", _SNAPSHOT_READY)])
    # user-1 tries to correct wallet owned by user-2
    result = _make_correction(storage).apply_correction(
        _base_policy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            expected_stored_revision=1,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_CORRECTION_BLOCK_REVISION_CONFLICT
    assert result.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED


# --- Result field preservation ---

def test_correction_result_wallet_binding_id_preserved_on_accept() -> None:
    storage = _make_storage_with([("wallet-abc", "user-1", _SNAPSHOT_READY)])
    result = _make_correction(storage).apply_correction(
        _base_policy(
            wallet_binding_id="wallet-abc",
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
            correction_snapshot=_SNAPSHOT_ALT,
            expected_stored_revision=1,
        )
    )
    assert result.wallet_binding_id == "wallet-abc"
    assert result.owner_user_id == "user-1"


def test_correction_result_wallet_binding_id_preserved_on_block() -> None:
    result = _make_correction().apply_correction(
        _base_policy(wallet_binding_id="wallet-x", wallet_active=False)
    )
    assert result.wallet_binding_id == "wallet-x"
    assert result.owner_user_id == "user-1"


def test_not_required_result_wallet_binding_and_owner_preserved() -> None:
    result = _make_correction().apply_correction(
        _base_policy(
            wallet_binding_id="wallet-z",
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_MATCH,
        )
    )
    assert result.wallet_binding_id == "wallet-z"
    assert result.owner_user_id == "user-1"
    assert result.success is True
