from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_READ_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_READ_BLOCK_NOT_FOUND,
    WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateReadPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
)


def _base_read_policy() -> WalletStateReadPolicy:
    return WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )


def _base_storage_policy() -> WalletStateStoragePolicy:
    return WalletStateStoragePolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="user-1",
        wallet_active=True,
        state_snapshot={
            "wallet_status": "ready",
            "available_balance": 200.0,
            "nonce": 5,
        },
    )


def test_phase6_5_3_read_state_returns_stored_snapshot() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(_base_storage_policy())

    result = boundary.read_state(_base_read_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.state_found is True
    assert result.stored_revision == 1
    assert result.state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 200.0,
        "nonce": 5,
    }


def test_phase6_5_3_read_state_reflects_latest_revision() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(_base_storage_policy())
    second_policy = WalletStateStoragePolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="user-1",
        wallet_active=True,
        state_snapshot={
            "wallet_status": "suspended",
            "available_balance": 50.0,
            "nonce": 6,
        },
    )
    boundary.store_state(second_policy)

    result = boundary.read_state(_base_read_policy())

    assert result.success is True
    assert result.stored_revision == 2
    assert result.state_snapshot == {
        "wallet_status": "suspended",
        "available_balance": 50.0,
        "nonce": 6,
    }


def test_phase6_5_3_read_state_blocks_when_no_state_stored() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.read_state(_base_read_policy())

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_NOT_FOUND
    assert result.state_found is False
    assert result.state_snapshot is None
    assert result.stored_revision is None


def test_phase6_5_3_read_state_blocks_inactive_wallet() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(_base_storage_policy())
    policy = WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=False,
    )

    result = boundary.read_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE
    assert result.state_found is False
    assert result.state_snapshot is None
    assert result.stored_revision is None


def test_phase6_5_3_read_state_blocks_ownership_mismatch() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(_base_storage_policy())
    policy = WalletStateReadPolicy(
        wallet_binding_id="wb-phase6-5-3",
        owner_user_id="user-1",
        requested_by_user_id="user-999",
        wallet_active=True,
    )

    result = boundary.read_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH
    assert result.state_found is False
    assert result.state_snapshot is None
    assert result.stored_revision is None


def test_phase6_5_3_read_state_blocks_invalid_contract_empty_binding_id() -> None:
    boundary = WalletStateStorageBoundary()
    policy = WalletStateReadPolicy(
        wallet_binding_id="",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )

    result = boundary.read_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_INVALID_CONTRACT
    assert result.state_found is False
    assert result.state_snapshot is None
    assert result.stored_revision is None
    assert result.notes == {"contract_error": "wallet_binding_id_required"}


def test_phase6_5_3_read_state_snapshot_is_independent_copy() -> None:
    """Mutating the returned snapshot must not affect the stored state."""
    boundary = WalletStateStorageBoundary()
    boundary.store_state(_base_storage_policy())

    result = boundary.read_state(_base_read_policy())
    assert result.state_snapshot is not None
    result.state_snapshot["available_balance"] = 0.0  # type: ignore[index]

    result_again = boundary.read_state(_base_read_policy())
    assert result_again.state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 200.0,
        "nonce": 5,
    }
