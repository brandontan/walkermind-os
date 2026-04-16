from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_READ_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_READ_BLOCK_NOT_FOUND,
    WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE,
    WALLET_STATE_STORAGE_BLOCK_OWNERSHIP_CONFLICT,
    WalletStateReadBoundary,
    WalletStateReadPolicy,
    WalletStateStoragePolicy,
)


def _base_storage_policy() -> WalletStateStoragePolicy:
    return WalletStateStoragePolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="owner-1",
        wallet_active=True,
        state_snapshot={
            "wallet_status": "ready",
            "available_balance": 100.0,
            "nonce": 9,
        },
    )


def test_phase6_5_3_owner_aware_store_and_read_success() -> None:
    boundary = WalletStateReadBoundary()
    store_result = boundary.store_state(_base_storage_policy())

    read_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="owner-1",
            requested_by_user_id="owner-1",
            wallet_active=True,
        )
    )

    assert store_result.success is True
    assert store_result.stored_revision == 1
    assert read_result.success is True
    assert read_result.blocked_reason is None
    assert read_result.state_found is True
    assert read_result.stored_revision == 1
    assert read_result.state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 100.0,
        "nonce": 9,
    }


def test_phase6_5_3_blocks_cross_owner_overwrite_for_same_wallet_binding_id() -> None:
    boundary = WalletStateReadBoundary()
    owner_1_result = boundary.store_state(_base_storage_policy())

    owner_2_result = boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="owner-2",
            wallet_active=True,
            state_snapshot={
                "wallet_status": "ready",
                "available_balance": 55.0,
                "nonce": 1,
            },
        )
    )

    assert owner_1_result.success is True
    assert owner_2_result.success is False
    assert owner_2_result.blocked_reason == WALLET_STATE_STORAGE_BLOCK_OWNERSHIP_CONFLICT
    assert owner_2_result.notes == {"existing_owner_user_id": "owner-1"}


def test_phase6_5_3_blocks_contract_ownership_and_activity_failures() -> None:
    boundary = WalletStateReadBoundary()

    invalid_contract_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="",
            owner_user_id="owner-1",
            requested_by_user_id="owner-1",
            wallet_active=True,
        )
    )
    ownership_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="owner-1",
            requested_by_user_id="owner-2",
            wallet_active=True,
        )
    )
    inactive_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="owner-1",
            requested_by_user_id="owner-1",
            wallet_active=False,
        )
    )

    assert invalid_contract_result.success is False
    assert invalid_contract_result.blocked_reason == WALLET_STATE_READ_BLOCK_INVALID_CONTRACT
    assert ownership_result.success is False
    assert ownership_result.blocked_reason == WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH
    assert inactive_result.success is False
    assert inactive_result.blocked_reason == WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE


def test_phase6_5_3_returns_deterministic_not_found_for_missing_owner_scoped_state() -> None:
    boundary = WalletStateReadBoundary()

    missing_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3-missing",
            owner_user_id="owner-1",
            requested_by_user_id="owner-1",
            wallet_active=True,
        )
    )

    assert missing_result.success is False
    assert missing_result.blocked_reason == WALLET_STATE_READ_BLOCK_NOT_FOUND
    assert missing_result.state_found is False
    assert missing_result.state_snapshot is None
    assert missing_result.stored_revision is None
    assert missing_result.notes == {"lookup_key": "wb-phase6-5-3-missing"}
