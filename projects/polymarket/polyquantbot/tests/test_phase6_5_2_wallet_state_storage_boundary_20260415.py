from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_STORAGE_BLOCK_INVALID_STATE,
    WALLET_STATE_STORAGE_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
)


def _base_policy() -> WalletStateStoragePolicy:
    return WalletStateStoragePolicy(
        wallet_binding_id="wb-phase6-5-2",
        owner_user_id="user-1",
        wallet_active=True,
        state_snapshot={
            "wallet_status": "ready",
            "available_balance": 125.50,
            "nonce": 3,
        },
    )


def test_phase6_5_2_wallet_state_storage_success_is_deterministic() -> None:
    boundary = WalletStateStorageBoundary()

    result_first = boundary.store_state(_base_policy())
    result_second = boundary.store_state(_base_policy())

    assert result_first.success is True
    assert result_first.blocked_reason is None
    assert result_first.state_stored is True
    assert result_first.stored_revision == 1
    assert result_second.success is True
    assert result_second.state_stored is True
    assert result_second.stored_revision == 2


def test_phase6_5_2_blocks_inactive_wallet_state_storage() -> None:
    boundary = WalletStateStorageBoundary()
    policy = WalletStateStoragePolicy(
        wallet_binding_id="wb-phase6-5-2",
        owner_user_id="user-1",
        wallet_active=False,
        state_snapshot={
            "wallet_status": "ready",
            "available_balance": 20.0,
            "nonce": 1,
        },
    )

    result = boundary.store_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_STORAGE_BLOCK_WALLET_NOT_ACTIVE
    assert result.state_stored is False
    assert result.stored_revision is None


def test_phase6_5_2_blocks_invalid_wallet_state_snapshot() -> None:
    boundary = WalletStateStorageBoundary()
    policy = WalletStateStoragePolicy(
        wallet_binding_id="wb-phase6-5-2",
        owner_user_id="user-1",
        wallet_active=True,
        state_snapshot={
            "wallet_status": "ready",
            "available_balance": -1.0,
            "nonce": 1,
        },
    )

    result = boundary.store_state(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_STORAGE_BLOCK_INVALID_STATE
    assert result.state_stored is False
    assert result.stored_revision is None
    assert result.notes == {"state_error": "available_balance_negative"}
