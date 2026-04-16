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


def _storage_policy() -> WalletStateStoragePolicy:
    return WalletStateStoragePolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="owner-1",
        wallet_active=True,
        state_snapshot={
            "wallet_status": "ready",
            "available_balance": 210.75,
            "nonce": 4,
        },
    )


def _read_policy() -> WalletStateReadPolicy:
    return WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="owner-1",
        requested_by_user_id="owner-1",
        wallet_active=True,
    )


def test_phase6_5_3_reads_stored_wallet_state_through_boundary() -> None:
    storage_boundary = WalletStateStorageBoundary()
    read_boundary = WalletStateReadBoundary(storage_boundary)
    storage_boundary.store_state(_storage_policy())

    result = read_boundary.read_state(_read_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.state_found is True
    assert result.stored_revision == 1
    assert result.state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 210.75,
        "nonce": 4,
    }


def test_phase6_5_3_blocks_read_when_wallet_not_active() -> None:
    storage_boundary = WalletStateStorageBoundary()
    read_boundary = WalletStateReadBoundary(storage_boundary)
    policy = WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="owner-1",
        requested_by_user_id="owner-1",
        wallet_active=False,
    )

    result = read_boundary.read_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE
    assert result.state_found is False
    assert result.stored_revision is None


def test_phase6_5_3_blocks_read_when_state_not_found() -> None:
    storage_boundary = WalletStateStorageBoundary()
    read_boundary = WalletStateReadBoundary(storage_boundary)

    result = read_boundary.read_state(_read_policy())

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_STATE_NOT_FOUND
    assert result.state_found is False
    assert result.state_snapshot is None


def test_phase6_5_3_blocks_read_on_requestor_ownership_mismatch() -> None:
    storage_boundary = WalletStateStorageBoundary()
    read_boundary = WalletStateReadBoundary(storage_boundary)
    storage_boundary.store_state(_storage_policy())
    policy = WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="owner-1",
        requested_by_user_id="owner-2",
        wallet_active=True,
    )

    result = read_boundary.read_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH
    assert result.state_found is False
    assert result.state_snapshot is None


def test_phase6_5_3_blocks_read_when_stored_owner_differs() -> None:
    storage_boundary = WalletStateStorageBoundary()
    read_boundary = WalletStateReadBoundary(storage_boundary)
    storage_boundary.store_state(_storage_policy())
    policy = WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="owner-2",
        requested_by_user_id="owner-2",
        wallet_active=True,
    )

    result = read_boundary.read_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH
    assert result.state_found is False
    assert result.state_snapshot is None
