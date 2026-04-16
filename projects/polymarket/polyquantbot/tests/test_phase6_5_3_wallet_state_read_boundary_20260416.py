from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_READ_BLOCK_STATE_NOT_FOUND,
    WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateReadBoundary,
    WalletStateReadPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
)


def _seed_wallet_state(boundary: WalletStateStorageBoundary) -> None:
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-owner",
            wallet_active=True,
            state_snapshot={
                "wallet_status": "ready",
                "available_balance": 100.0,
                "nonce": 11,
            },
        )
    )


def _base_read_policy() -> WalletStateReadPolicy:
    return WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="user-owner",
        requested_by_user_id="user-owner",
        wallet_active=True,
    )


def test_phase6_5_3_wallet_state_read_success_returns_stored_snapshot() -> None:
    storage_boundary = WalletStateStorageBoundary()
    _seed_wallet_state(storage_boundary)
    read_boundary = WalletStateReadBoundary(storage_boundary)

    result = read_boundary.read_state(_base_read_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.state_read is True
    assert result.stored_revision == 1
    assert result.state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 100.0,
        "nonce": 11,
    }


def test_phase6_5_3_wallet_state_read_blocks_owner_mismatch() -> None:
    storage_boundary = WalletStateStorageBoundary()
    _seed_wallet_state(storage_boundary)
    read_boundary = WalletStateReadBoundary(storage_boundary)

    result = read_boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-owner",
            requested_by_user_id="user-other",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH
    assert result.state_read is False
    assert result.state_snapshot is None


def test_phase6_5_3_wallet_state_read_blocks_inactive_wallet() -> None:
    storage_boundary = WalletStateStorageBoundary()
    _seed_wallet_state(storage_boundary)
    read_boundary = WalletStateReadBoundary(storage_boundary)

    result = read_boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-owner",
            requested_by_user_id="user-owner",
            wallet_active=False,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE
    assert result.state_read is False
    assert result.state_snapshot is None


def test_phase6_5_3_wallet_state_read_blocks_missing_or_wrong_owner_state() -> None:
    storage_boundary = WalletStateStorageBoundary()
    _seed_wallet_state(storage_boundary)
    read_boundary = WalletStateReadBoundary(storage_boundary)

    wrong_owner_result = read_boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-other",
            requested_by_user_id="user-other",
            wallet_active=True,
        )
    )
    missing_wallet_result = read_boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-missing",
            owner_user_id="user-owner",
            requested_by_user_id="user-owner",
            wallet_active=True,
        )
    )

    assert wrong_owner_result.success is False
    assert wrong_owner_result.blocked_reason == WALLET_STATE_READ_BLOCK_STATE_NOT_FOUND
    assert missing_wallet_result.success is False
    assert missing_wallet_result.blocked_reason == WALLET_STATE_READ_BLOCK_STATE_NOT_FOUND
