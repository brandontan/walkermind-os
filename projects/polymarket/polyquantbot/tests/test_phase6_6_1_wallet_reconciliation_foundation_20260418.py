from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT,
    WALLET_RECONCILIATION_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_RECONCILIATION_BLOCK_WALLET_NOT_ACTIVE,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
    WalletLifecycleReconciliationBoundary,
    WalletReconciliationPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
    _validate_reconciliation_policy,
)

_SNAPSHOT_READY = {"wallet_status": "ready", "available_balance": 100.0, "nonce": 1}


def _make_storage(
    *,
    wallet_binding_id: str = "wb-661-a",
    owner_user_id: str = "user-1",
    snapshot: dict | None = None,
) -> WalletStateStorageBoundary:
    boundary = WalletStateStorageBoundary()
    if snapshot is not None:
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


def _make_recon_boundary(
    storage: WalletStateStorageBoundary | None = None,
) -> WalletLifecycleReconciliationBoundary:
    return WalletLifecycleReconciliationBoundary(storage or WalletStateStorageBoundary())


def _base_policy(
    *,
    wallet_binding_id: str = "wb-661-a",
    owner_user_id: str = "user-1",
    expected_snapshot: dict | None = None,
    expected_revision: int | None = None,
) -> WalletReconciliationPolicy:
    return WalletReconciliationPolicy(
        wallet_binding_id=wallet_binding_id,
        owner_user_id=owner_user_id,
        requested_by_user_id=owner_user_id,
        wallet_active=True,
        expected_state_snapshot=expected_snapshot if expected_snapshot is not None else dict(_SNAPSHOT_READY),
        expected_revision=expected_revision,
    )


# ---------------------------------------------------------------------------
# Block contracts
# ---------------------------------------------------------------------------

def test_phase6_6_1_blocks_invalid_contract_blank_wallet_binding_id() -> None:
    recon = _make_recon_boundary()
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="   ",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            expected_state_snapshot=dict(_SNAPSHOT_READY),
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT
    assert result.reconciliation_outcome is None
    assert result.notes is not None
    assert result.notes["contract_error"] == "wallet_binding_id_required"


def test_phase6_6_1_blocks_invalid_contract_blank_owner_user_id() -> None:
    recon = _make_recon_boundary()
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="wb-661-a",
            owner_user_id="",
            requested_by_user_id="user-1",
            wallet_active=True,
            expected_state_snapshot=dict(_SNAPSHOT_READY),
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "owner_user_id_required"


def test_phase6_6_1_blocks_invalid_contract_expected_snapshot_not_dict() -> None:
    recon = _make_recon_boundary()
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="wb-661-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            expected_state_snapshot=None,  # type: ignore[arg-type]
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "expected_state_snapshot_must_be_dict"


def test_phase6_6_1_blocks_invalid_contract_expected_revision_zero() -> None:
    recon = _make_recon_boundary()
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="wb-661-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            expected_state_snapshot=dict(_SNAPSHOT_READY),
            expected_revision=0,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "expected_revision_must_be_positive"


def test_phase6_6_1_blocks_ownership_mismatch() -> None:
    storage = _make_storage(snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="wb-661-a",
            owner_user_id="user-1",
            requested_by_user_id="user-2",
            wallet_active=True,
            expected_state_snapshot=dict(_SNAPSHOT_READY),
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BLOCK_OWNERSHIP_MISMATCH
    assert result.reconciliation_outcome is None


def test_phase6_6_1_blocks_wallet_not_active() -> None:
    storage = _make_storage(snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="wb-661-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
            expected_state_snapshot=dict(_SNAPSHOT_READY),
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BLOCK_WALLET_NOT_ACTIVE
    assert result.reconciliation_outcome is None


# ---------------------------------------------------------------------------
# Outcome: state_missing
# ---------------------------------------------------------------------------

def test_phase6_6_1_outcome_state_missing_when_no_stored_state() -> None:
    recon = _make_recon_boundary()
    result = recon.reconcile_wallet_state(_base_policy())
    assert result.success is True
    assert result.blocked_reason is None
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING
    assert result.stored_revision is None
    assert result.expected_revision is None


def test_phase6_6_1_outcome_state_missing_with_expected_revision_still_state_missing() -> None:
    recon = _make_recon_boundary()
    result = recon.reconcile_wallet_state(_base_policy(expected_revision=3))
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING
    assert result.stored_revision is None
    assert result.expected_revision == 3


# ---------------------------------------------------------------------------
# Outcome: revision_mismatch
# ---------------------------------------------------------------------------

def test_phase6_6_1_outcome_revision_mismatch_when_stored_revision_differs() -> None:
    storage = _make_storage(snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        _base_policy(expected_snapshot=dict(_SNAPSHOT_READY), expected_revision=99)
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH
    assert result.stored_revision == 1
    assert result.expected_revision == 99
    assert result.notes is not None
    assert result.notes["stored_revision"] == 1
    assert result.notes["expected_revision"] == 99


def test_phase6_6_1_outcome_revision_mismatch_takes_priority_over_snapshot_mismatch() -> None:
    storage = _make_storage(snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    different_snapshot = {"wallet_status": "suspended", "available_balance": 0.0, "nonce": 99}
    result = recon.reconcile_wallet_state(
        _base_policy(expected_snapshot=different_snapshot, expected_revision=5)
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH


# ---------------------------------------------------------------------------
# Outcome: snapshot_mismatch
# ---------------------------------------------------------------------------

def test_phase6_6_1_outcome_snapshot_mismatch_when_snapshot_differs() -> None:
    storage = _make_storage(snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1})
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        _base_policy(
            expected_snapshot={"wallet_status": "ready", "available_balance": 999.0, "nonce": 1}
        )
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH
    assert result.stored_revision == 1
    assert result.notes is not None
    assert "available_balance" in result.notes["mismatch_keys"]


def test_phase6_6_1_outcome_snapshot_mismatch_reports_all_mismatched_keys() -> None:
    storage = _make_storage(
        snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1}
    )
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        _base_policy(
            expected_snapshot={"wallet_status": "suspended", "available_balance": 200.0, "nonce": 1}
        )
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH
    assert result.notes is not None
    assert sorted(result.notes["mismatch_keys"]) == ["available_balance", "wallet_status"]


def test_phase6_6_1_outcome_snapshot_mismatch_with_correct_revision_still_mismatch() -> None:
    storage = _make_storage(snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        _base_policy(
            expected_snapshot={"wallet_status": "suspended", "available_balance": 100.0, "nonce": 1},
            expected_revision=1,
        )
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH


# ---------------------------------------------------------------------------
# Outcome: match
# ---------------------------------------------------------------------------

def test_phase6_6_1_outcome_match_when_snapshot_matches_no_revision_check() -> None:
    storage = _make_storage(snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(_base_policy(expected_snapshot=dict(_SNAPSHOT_READY)))
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH
    assert result.blocked_reason is None
    assert result.stored_revision == 1
    assert result.expected_revision is None
    assert result.notes is not None
    assert result.notes["stored_revision"] == 1


def test_phase6_6_1_outcome_match_when_snapshot_and_revision_both_match() -> None:
    storage = _make_storage(snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        _base_policy(expected_snapshot=dict(_SNAPSHOT_READY), expected_revision=1)
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH
    assert result.stored_revision == 1
    assert result.expected_revision == 1


def test_phase6_6_1_outcome_match_after_multiple_stores() -> None:
    storage = WalletStateStorageBoundary()
    for nonce in range(1, 4):
        storage.store_state(
            WalletStateStoragePolicy(
                wallet_binding_id="wb-661-a",
                owner_user_id="user-1",
                wallet_active=True,
                state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": nonce},
            )
        )
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        _base_policy(
            expected_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 3},
            expected_revision=3,
        )
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH
    assert result.stored_revision == 3


# ---------------------------------------------------------------------------
# Owner isolation
# ---------------------------------------------------------------------------

def test_phase6_6_1_reconciliation_does_not_expose_other_owner_state() -> None:
    storage = _make_storage(wallet_binding_id="wb-661-a", owner_user_id="user-2", snapshot=dict(_SNAPSHOT_READY))
    recon = _make_recon_boundary(storage)
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="wb-661-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            expected_state_snapshot=dict(_SNAPSHOT_READY),
        )
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING


# ---------------------------------------------------------------------------
# Validator unit test
# ---------------------------------------------------------------------------

def test_phase6_6_1_validator_rejects_bool_expected_revision() -> None:
    policy = WalletReconciliationPolicy(
        wallet_binding_id="wb-661-a",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
        expected_state_snapshot=dict(_SNAPSHOT_READY),
        expected_revision=True,  # type: ignore[arg-type]
    )
    error = _validate_reconciliation_policy(policy)
    assert error == "expected_revision_must_be_int_or_none"


# ---------------------------------------------------------------------------
# Prior phase preservation smoke test
# ---------------------------------------------------------------------------

def test_phase6_6_1_prior_phase_read_state_batch_still_passes() -> None:
    from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
        WalletStateReadBatchPolicy,
    )
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-compat-6510",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 50.0, "nonce": 1},
        )
    )
    batch_result = boundary.read_state_batch(
        WalletStateReadBatchPolicy(
            wallet_binding_ids=["wb-compat-6510"],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert batch_result.success is True
    assert batch_result.entries is not None
    assert batch_result.entries[0].state_found is True
