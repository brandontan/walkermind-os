from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_READ_BATCH_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_READ_BATCH_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_READ_BATCH_BLOCK_TOO_MANY,
    WALLET_STATE_READ_BATCH_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateReadBatchPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
    _validate_state_read_batch_policy,
)


def _store_state(
    *,
    boundary: WalletStateStorageBoundary,
    wallet_binding_id: str,
    owner_user_id: str = "user-1",
    nonce: int = 1,
    available_balance: float = 100.0,
) -> None:
    result = boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id=wallet_binding_id,
            owner_user_id=owner_user_id,
            wallet_active=True,
            state_snapshot={
                "wallet_status": "ready",
                "available_balance": available_balance,
                "nonce": nonce,
            },
        ),
    )
    assert result.success is True


def _base_batch_read_policy(
    wallet_binding_ids: list[str] | None = None,
) -> WalletStateReadBatchPolicy:
    return WalletStateReadBatchPolicy(
        wallet_binding_ids=wallet_binding_ids or ["wb-phase6-5-10-a", "wb-phase6-5-10-b"],
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )


def test_phase6_5_10_read_batch_success_returns_full_snapshots_in_input_order() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-a", nonce=1, available_balance=100.0)
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-a", nonce=2, available_balance=200.0)
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-b", nonce=1, available_balance=50.0)

    result = boundary.read_state_batch(
        _base_batch_read_policy(["wb-phase6-5-10-b", "wb-phase6-5-10-a"])
    )

    assert result.success is True
    assert result.blocked_reason is None
    assert result.entries is not None
    assert [e.wallet_binding_id for e in result.entries] == ["wb-phase6-5-10-b", "wb-phase6-5-10-a"]
    assert [e.state_found for e in result.entries] == [True, True]
    assert [e.stored_revision for e in result.entries] == [1, 2]
    entry_b = result.entries[0]
    assert entry_b.state_snapshot == {"wallet_status": "ready", "available_balance": 50.0, "nonce": 1}
    entry_a = result.entries[1]
    assert entry_a.state_snapshot == {"wallet_status": "ready", "available_balance": 200.0, "nonce": 2}


def test_phase6_5_10_read_batch_snapshot_is_copy_not_reference() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-a")

    result = boundary.read_state_batch(_base_batch_read_policy(["wb-phase6-5-10-a"]))

    assert result.success is True
    assert result.entries is not None
    snapshot = result.entries[0].state_snapshot
    assert snapshot is not None
    snapshot["tampered"] = True
    result2 = boundary.read_state_batch(_base_batch_read_policy(["wb-phase6-5-10-a"]))
    assert result2.entries is not None
    assert "tampered" not in result2.entries[0].state_snapshot


def test_phase6_5_10_read_batch_missing_entries_are_deterministic() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-a")
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-other-owner", owner_user_id="user-2")

    result = boundary.read_state_batch(
        _base_batch_read_policy(
            [
                "wb-phase6-5-10-a",
                "wb-phase6-5-10-missing",
                "wb-phase6-5-10-other-owner",
            ],
        ),
    )

    assert result.success is True
    assert result.entries is not None
    assert [e.wallet_binding_id for e in result.entries] == [
        "wb-phase6-5-10-a",
        "wb-phase6-5-10-missing",
        "wb-phase6-5-10-other-owner",
    ]
    assert [e.state_found for e in result.entries] == [True, False, False]
    assert [e.stored_revision for e in result.entries] == [1, None, None]
    assert [e.state_snapshot for e in result.entries] == [
        {"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        None,
        None,
    ]
    assert result.notes == {
        "entry_count": 3,
        "missing_wallet_binding_ids": [
            "wb-phase6-5-10-missing",
            "wb-phase6-5-10-other-owner",
        ],
    }


def test_phase6_5_10_read_batch_all_missing_returns_success_with_none_snapshots() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.read_state_batch(
        _base_batch_read_policy(["wb-phase6-5-10-missing-1", "wb-phase6-5-10-missing-2"])
    )

    assert result.success is True
    assert result.entries is not None
    assert all(e.state_found is False for e in result.entries)
    assert all(e.state_snapshot is None for e in result.entries)
    assert all(e.stored_revision is None for e in result.entries)
    assert result.notes is not None
    assert result.notes["missing_wallet_binding_ids"] == [
        "wb-phase6-5-10-missing-1",
        "wb-phase6-5-10-missing-2",
    ]


def test_phase6_5_10_read_batch_blocks_invalid_contract_empty_list() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.read_state_batch(
        WalletStateReadBatchPolicy(
            wallet_binding_ids=[],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BATCH_BLOCK_INVALID_CONTRACT
    assert result.entries is None
    assert result.notes == {"contract_error": "wallet_binding_ids_required"}


def test_phase6_5_10_read_batch_blocks_invalid_contract_blank_entry() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.read_state_batch(
        WalletStateReadBatchPolicy(
            wallet_binding_ids=["wb-phase6-5-10-a", "   "],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BATCH_BLOCK_INVALID_CONTRACT
    assert result.entries is None


def test_phase6_5_10_read_batch_blocks_ownership_mismatch() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-a")

    result = boundary.read_state_batch(
        WalletStateReadBatchPolicy(
            wallet_binding_ids=["wb-phase6-5-10-a"],
            owner_user_id="user-1",
            requested_by_user_id="user-2",
            wallet_active=True,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BATCH_BLOCK_OWNERSHIP_MISMATCH
    assert result.entries is None


def test_phase6_5_10_read_batch_blocks_wallet_not_active() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-a")

    result = boundary.read_state_batch(
        WalletStateReadBatchPolicy(
            wallet_binding_ids=["wb-phase6-5-10-a"],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BATCH_BLOCK_WALLET_NOT_ACTIVE
    assert result.entries is None


def test_phase6_5_10_read_batch_blocks_too_many_wallet_binding_ids() -> None:
    boundary = WalletStateStorageBoundary()
    wallet_binding_ids = [f"wb-phase6-5-10-{index}" for index in range(101)]
    policy = WalletStateReadBatchPolicy(
        wallet_binding_ids=wallet_binding_ids,
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )

    assert _validate_state_read_batch_policy(policy) == "wallet_binding_ids_too_many"

    result = boundary.read_state_batch(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BATCH_BLOCK_TOO_MANY
    assert result.entries == []
    assert result.owner_user_id == "user-1"


def test_phase6_5_10_read_batch_does_not_expose_other_owner_snapshots() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-shared", owner_user_id="user-2")

    result = boundary.read_state_batch(
        WalletStateReadBatchPolicy(
            wallet_binding_ids=["wb-shared"],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        ),
    )

    assert result.success is True
    assert result.entries is not None
    assert result.entries[0].state_found is False
    assert result.entries[0].state_snapshot is None
    assert result.entries[0].stored_revision is None


def test_phase6_5_10_read_batch_single_entry_success() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-10-single", nonce=5, available_balance=999.0)

    result = boundary.read_state_batch(
        _base_batch_read_policy(["wb-phase6-5-10-single"])
    )

    assert result.success is True
    assert result.entries is not None
    assert len(result.entries) == 1
    assert result.entries[0].state_found is True
    assert result.entries[0].stored_revision == 1
    assert result.entries[0].state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 999.0,
        "nonce": 5,
    }
    assert result.notes == {"entry_count": 1, "missing_wallet_binding_ids": []}


def test_phase6_5_10_prior_phase_read_state_still_passes() -> None:
    boundary = WalletStateStorageBoundary()
    from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
        WalletStateReadPolicy,
    )
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-3-compat",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 50.0, "nonce": 1},
        )
    )
    read_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3-compat",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert read_result.success is True
    assert read_result.state_found is True
    assert read_result.state_snapshot == {"wallet_status": "ready", "available_balance": 50.0, "nonce": 1}
