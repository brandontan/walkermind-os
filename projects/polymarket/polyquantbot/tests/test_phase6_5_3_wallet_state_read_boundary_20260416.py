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


def _seed_state(storage: WalletStateStorageBoundary) -> None:
    result = storage.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={
                "wallet_status": "ready",
                "available_balance": 101.25,
                "nonce": 8,
            },
        )
    )
    assert result.success is True


def test_phase6_5_3_wallet_state_read_success_for_owner() -> None:
    storage = WalletStateStorageBoundary()
    _seed_state(storage)
    boundary = WalletStateReadBoundary(storage)

    result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )

    assert result.success is True
    assert result.blocked_reason is None
    assert result.state_read is True
    assert result.stored_revision == 1
    assert result.state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 101.25,
        "nonce": 8,
    }


def test_phase6_5_3_wallet_state_read_blocks_non_owner() -> None:
    storage = WalletStateStorageBoundary()
    _seed_state(storage)
    boundary = WalletStateReadBoundary(storage)

    result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-1",
            requested_by_user_id="user-2",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH
    assert result.state_read is False
    assert result.stored_revision is None


def test_phase6_5_3_wallet_state_read_blocks_inactive_wallet() -> None:
    storage = WalletStateStorageBoundary()
    _seed_state(storage)
    boundary = WalletStateReadBoundary(storage)

    result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE
    assert result.state_read is False


def test_phase6_5_3_wallet_state_read_blocks_unknown_wallet_or_owner() -> None:
    storage = WalletStateStorageBoundary()
    _seed_state(storage)
    boundary = WalletStateReadBoundary(storage)

    unknown_wallet_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-missing",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    wrong_owner_result = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-3",
            owner_user_id="user-2",
            requested_by_user_id="user-2",
            wallet_active=True,
        )
    )

    assert unknown_wallet_result.success is False
    assert unknown_wallet_result.blocked_reason == WALLET_STATE_READ_BLOCK_STATE_NOT_FOUND
    assert wrong_owner_result.success is False
    assert wrong_owner_result.blocked_reason == WALLET_STATE_READ_BLOCK_STATE_NOT_FOUND
