from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT,
    WALLET_RECONCILIATION_BATCH_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_RECONCILIATION_BATCH_BLOCK_TOO_MANY,
    WALLET_RECONCILIATION_BATCH_BLOCK_WALLET_NOT_ACTIVE,
    WALLET_RECONCILIATION_BATCH_MAX_SIZE,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
    WalletBatchReconciliationEntry,
    WalletBatchReconciliationPolicy,
    WalletLifecycleReconciliationBoundary,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
    _validate_batch_reconciliation_policy,
)

_SNAPSHOT_READY = {"wallet_status": "ready", "available_balance": 100.0, "nonce": 1}
_SNAPSHOT_ALT = {"wallet_status": "suspended", "available_balance": 0.0, "nonce": 99}


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


def _make_recon(storage: WalletStateStorageBoundary | None = None) -> WalletLifecycleReconciliationBoundary:
    return WalletLifecycleReconciliationBoundary(storage or WalletStateStorageBoundary())


def _base_policy(
    *,
    entries: list[WalletBatchReconciliationEntry],
    owner_user_id: str = "user-1",
    requested_by_user_id: str | None = None,
    wallet_active: bool = True,
) -> WalletBatchReconciliationPolicy:
    return WalletBatchReconciliationPolicy(
        entries=entries,
        owner_user_id=owner_user_id,
        requested_by_user_id=requested_by_user_id if requested_by_user_id is not None else owner_user_id,
        wallet_active=wallet_active,
    )


def _entry(
    wallet_binding_id: str,
    snapshot: dict | None = None,
    expected_revision: int | None = None,
) -> WalletBatchReconciliationEntry:
    return WalletBatchReconciliationEntry(
        wallet_binding_id=wallet_binding_id,
        expected_state_snapshot=snapshot if snapshot is not None else dict(_SNAPSHOT_READY),
        expected_revision=expected_revision,
    )


# ---------------------------------------------------------------------------
# Block contracts — batch-level gate
# ---------------------------------------------------------------------------

def test_phase6_6_2_blocks_invalid_contract_empty_entries() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        WalletBatchReconciliationPolicy(
            entries=[],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT
    assert result.entries is None
    assert result.notes is not None
    assert result.notes["contract_error"] == "entries_required"


def test_phase6_6_2_blocks_invalid_contract_entry_blank_wallet_binding_id() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        WalletBatchReconciliationPolicy(
            entries=[
                WalletBatchReconciliationEntry(
                    wallet_binding_id="   ",
                    expected_state_snapshot=dict(_SNAPSHOT_READY),
                )
            ],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "wallet_binding_id_required"


def test_phase6_6_2_blocks_invalid_contract_entry_snapshot_not_dict() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        WalletBatchReconciliationPolicy(
            entries=[
                WalletBatchReconciliationEntry(
                    wallet_binding_id="wb-662-a",
                    expected_state_snapshot=None,  # type: ignore[arg-type]
                )
            ],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "expected_state_snapshot_must_be_dict"


def test_phase6_6_2_blocks_invalid_contract_entry_expected_revision_zero() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a", expected_revision=0)])
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "expected_revision_must_be_positive"


def test_phase6_6_2_blocks_invalid_contract_entry_expected_revision_bool() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        WalletBatchReconciliationPolicy(
            entries=[
                WalletBatchReconciliationEntry(
                    wallet_binding_id="wb-662-a",
                    expected_state_snapshot=dict(_SNAPSHOT_READY),
                    expected_revision=True,  # type: ignore[arg-type]
                )
            ],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "expected_revision_must_be_int_or_none"


def test_phase6_6_2_blocks_invalid_contract_blank_owner_user_id() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        WalletBatchReconciliationPolicy(
            entries=[_entry("wb-662-a")],
            owner_user_id="",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT
    assert result.notes is not None
    assert result.notes["contract_error"] == "owner_user_id_required"


def test_phase6_6_2_blocks_too_many_entries() -> None:
    recon = _make_recon()
    entries = [_entry(f"wb-{i}") for i in range(WALLET_RECONCILIATION_BATCH_MAX_SIZE + 1)]
    result = recon.reconcile_wallet_state_batch(_base_policy(entries=entries))
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_TOO_MANY
    assert result.entries is None


def test_phase6_6_2_blocks_ownership_mismatch() -> None:
    storage = _make_storage_with([("wb-662-a", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        WalletBatchReconciliationPolicy(
            entries=[_entry("wb-662-a")],
            owner_user_id="user-1",
            requested_by_user_id="user-2",
            wallet_active=True,
        )
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_OWNERSHIP_MISMATCH
    assert result.entries is None


def test_phase6_6_2_blocks_wallet_not_active() -> None:
    storage = _make_storage_with([("wb-662-a", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a")], wallet_active=False)
    )
    assert result.success is False
    assert result.blocked_reason == WALLET_RECONCILIATION_BATCH_BLOCK_WALLET_NOT_ACTIVE
    assert result.entries is None


# ---------------------------------------------------------------------------
# Outcome: state_missing — per entry
# ---------------------------------------------------------------------------

def test_phase6_6_2_outcome_state_missing_when_no_stored_state() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-notfound")])
    )
    assert result.success is True
    assert result.blocked_reason is None
    assert result.entries is not None
    assert len(result.entries) == 1
    e = result.entries[0]
    assert e.wallet_binding_id == "wb-662-notfound"
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING
    assert e.stored_revision is None
    assert e.expected_revision is None


def test_phase6_6_2_outcome_state_missing_with_expected_revision() -> None:
    recon = _make_recon()
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-notfound", expected_revision=5)])
    )
    assert result.success is True
    assert result.entries is not None
    e = result.entries[0]
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING
    assert e.stored_revision is None
    assert e.expected_revision == 5


# ---------------------------------------------------------------------------
# Outcome: match — per entry
# ---------------------------------------------------------------------------

def test_phase6_6_2_outcome_match_when_snapshot_matches() -> None:
    storage = _make_storage_with([("wb-662-a", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a", dict(_SNAPSHOT_READY))])
    )
    assert result.success is True
    assert result.entries is not None
    e = result.entries[0]
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH
    assert e.stored_revision == 1
    assert e.expected_revision is None


def test_phase6_6_2_outcome_match_when_snapshot_and_revision_match() -> None:
    storage = _make_storage_with([("wb-662-a", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a", dict(_SNAPSHOT_READY), expected_revision=1)])
    )
    assert result.success is True
    assert result.entries is not None
    e = result.entries[0]
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH
    assert e.stored_revision == 1
    assert e.expected_revision == 1


# ---------------------------------------------------------------------------
# Outcome: revision_mismatch — per entry
# ---------------------------------------------------------------------------

def test_phase6_6_2_outcome_revision_mismatch_when_revision_differs() -> None:
    storage = _make_storage_with([("wb-662-a", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a", dict(_SNAPSHOT_READY), expected_revision=99)])
    )
    assert result.success is True
    assert result.entries is not None
    e = result.entries[0]
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH
    assert e.stored_revision == 1
    assert e.expected_revision == 99
    assert e.notes is not None
    assert e.notes["stored_revision"] == 1
    assert e.notes["expected_revision"] == 99


def test_phase6_6_2_revision_mismatch_takes_priority_over_snapshot_mismatch() -> None:
    storage = _make_storage_with([("wb-662-a", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a", dict(_SNAPSHOT_ALT), expected_revision=99)])
    )
    assert result.success is True
    assert result.entries is not None
    e = result.entries[0]
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH


# ---------------------------------------------------------------------------
# Outcome: snapshot_mismatch — per entry
# ---------------------------------------------------------------------------

def test_phase6_6_2_outcome_snapshot_mismatch_when_snapshot_differs() -> None:
    storage = _make_storage_with([("wb-662-a", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a", dict(_SNAPSHOT_ALT))])
    )
    assert result.success is True
    assert result.entries is not None
    e = result.entries[0]
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH
    assert e.stored_revision == 1
    assert e.notes is not None
    assert "available_balance" in e.notes["mismatch_keys"]
    assert "wallet_status" in e.notes["mismatch_keys"]
    assert "nonce" in e.notes["mismatch_keys"]


def test_phase6_6_2_snapshot_mismatch_reports_sorted_keys() -> None:
    stored_snap = {"wallet_status": "ready", "available_balance": 100.0, "nonce": 1}
    expected_snap = {"wallet_status": "suspended", "available_balance": 200.0, "nonce": 1}
    storage = _make_storage_with([("wb-662-a", "user-1", stored_snap)])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a", expected_snap)])
    )
    assert result.success is True
    assert result.entries is not None
    e = result.entries[0]
    assert e.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH
    assert e.notes is not None
    assert e.notes["mismatch_keys"] == ["available_balance", "wallet_status"]


# ---------------------------------------------------------------------------
# Deterministic input-order preservation
# ---------------------------------------------------------------------------

def test_phase6_6_2_deterministic_input_order_multi_entry() -> None:
    storage = _make_storage_with([
        ("wb-662-a", "user-1", dict(_SNAPSHOT_READY)),
        ("wb-662-b", "user-1", dict(_SNAPSHOT_ALT)),
    ])
    recon = _make_recon(storage)

    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[
            _entry("wb-662-notfound"),
            _entry("wb-662-a", dict(_SNAPSHOT_READY)),
            _entry("wb-662-b", dict(_SNAPSHOT_READY), expected_revision=99),
            _entry("wb-662-a", {"wallet_status": "suspended", "available_balance": 100.0, "nonce": 1}),
        ])
    )
    assert result.success is True
    assert result.entries is not None
    assert len(result.entries) == 4

    assert result.entries[0].wallet_binding_id == "wb-662-notfound"
    assert result.entries[0].reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING

    assert result.entries[1].wallet_binding_id == "wb-662-a"
    assert result.entries[1].reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH

    assert result.entries[2].wallet_binding_id == "wb-662-b"
    assert result.entries[2].reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH

    assert result.entries[3].wallet_binding_id == "wb-662-a"
    assert result.entries[3].reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH


def test_phase6_6_2_all_four_outcomes_in_one_batch() -> None:
    storage = _make_storage_with([
        ("wb-match", "user-1", dict(_SNAPSHOT_READY)),
        ("wb-rev", "user-1", dict(_SNAPSHOT_READY)),
        ("wb-snap", "user-1", dict(_SNAPSHOT_READY)),
    ])
    recon = _make_recon(storage)

    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[
            _entry("wb-match", dict(_SNAPSHOT_READY)),
            _entry("wb-missing"),
            _entry("wb-rev", dict(_SNAPSHOT_READY), expected_revision=99),
            _entry("wb-snap", {"wallet_status": "suspended", "available_balance": 100.0, "nonce": 1}),
        ])
    )
    assert result.success is True
    assert result.entries is not None
    outcomes = [e.reconciliation_outcome for e in result.entries]
    assert outcomes == [
        WALLET_RECONCILIATION_OUTCOME_MATCH,
        WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
        WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
        WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
    ]


# ---------------------------------------------------------------------------
# outcome_counts in notes
# ---------------------------------------------------------------------------

def test_phase6_6_2_notes_contain_accurate_outcome_counts() -> None:
    storage = _make_storage_with([
        ("wb-662-a", "user-1", dict(_SNAPSHOT_READY)),
        ("wb-662-b", "user-1", dict(_SNAPSHOT_READY)),
    ])
    recon = _make_recon(storage)

    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[
            _entry("wb-662-a", dict(_SNAPSHOT_READY)),
            _entry("wb-662-b", dict(_SNAPSHOT_READY), expected_revision=99),
            _entry("wb-662-notfound"),
        ])
    )
    assert result.success is True
    assert result.notes is not None
    assert result.notes["entry_count"] == 3
    counts = result.notes["outcome_counts"]
    assert counts[WALLET_RECONCILIATION_OUTCOME_MATCH] == 1
    assert counts[WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH] == 1
    assert counts[WALLET_RECONCILIATION_OUTCOME_STATE_MISSING] == 1
    assert counts[WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH] == 0


# ---------------------------------------------------------------------------
# Owner isolation
# ---------------------------------------------------------------------------

def test_phase6_6_2_owner_isolation_cross_owner_returns_state_missing() -> None:
    storage = _make_storage_with([("wb-662-a", "user-2", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state_batch(
        _base_policy(entries=[_entry("wb-662-a")], owner_user_id="user-1")
    )
    assert result.success is True
    assert result.entries is not None
    assert result.entries[0].reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_STATE_MISSING


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------

def test_phase6_6_2_validator_rejects_blank_requested_by_user_id() -> None:
    policy = WalletBatchReconciliationPolicy(
        entries=[_entry("wb-662-a")],
        owner_user_id="user-1",
        requested_by_user_id="",
        wallet_active=True,
    )
    error = _validate_batch_reconciliation_policy(policy)
    assert error == "requested_by_user_id_required"


def test_phase6_6_2_validator_rejects_non_bool_wallet_active() -> None:
    policy = WalletBatchReconciliationPolicy(
        entries=[_entry("wb-662-a")],
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active="yes",  # type: ignore[arg-type]
    )
    error = _validate_batch_reconciliation_policy(policy)
    assert error == "wallet_active_must_be_bool"


def test_phase6_6_2_validator_accepts_valid_policy_no_revision() -> None:
    policy = WalletBatchReconciliationPolicy(
        entries=[_entry("wb-662-a")],
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )
    error = _validate_batch_reconciliation_policy(policy)
    assert error is None


def test_phase6_6_2_validator_accepts_valid_policy_with_revision() -> None:
    policy = WalletBatchReconciliationPolicy(
        entries=[_entry("wb-662-a", expected_revision=3)],
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )
    error = _validate_batch_reconciliation_policy(policy)
    assert error is None


# ---------------------------------------------------------------------------
# Prior phase preservation smoke tests
# ---------------------------------------------------------------------------

def test_phase6_6_2_prior_phase_single_reconcile_still_passes() -> None:
    from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
        WALLET_RECONCILIATION_OUTCOME_MATCH,
        WalletReconciliationPolicy,
    )
    storage = _make_storage_with([("wb-compat-661", "user-1", dict(_SNAPSHOT_READY))])
    recon = _make_recon(storage)
    result = recon.reconcile_wallet_state(
        WalletReconciliationPolicy(
            wallet_binding_id="wb-compat-661",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            expected_state_snapshot=dict(_SNAPSHOT_READY),
        )
    )
    assert result.success is True
    assert result.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH


def test_phase6_6_2_prior_phase_read_state_batch_still_passes() -> None:
    from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
        WalletStateReadBatchPolicy,
    )
    storage = _make_storage_with([("wb-compat-6510", "user-1", dict(_SNAPSHOT_READY))])
    batch_result = storage.read_state_batch(
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
