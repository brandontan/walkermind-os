from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_CLEAR_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_CLEAR_BLOCK_NOT_FOUND,
    WALLET_STATE_CLEAR_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_CLEAR_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateClearPolicy,
    WalletStateReadPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
)


def _base_clear_policy() -> WalletStateClearPolicy:
    return WalletStateClearPolicy(
        wallet_binding_id="wb-phase6-5-4-a",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )


def test_phase6_5_4_clear_state_removes_named_wallet_binding_only() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-4-a",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        )
    )
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-4-b",
            owner_user_id="user-2",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 50.0, "nonce": 9},
        )
    )

    clear_result = boundary.clear_state(_base_clear_policy())

    assert clear_result.success is True
    assert clear_result.blocked_reason is None
    assert clear_result.state_cleared is True
    assert clear_result.cleared_revision == 1

    cleared_read = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-4-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )
    assert cleared_read.success is False
    assert cleared_read.blocked_reason == WALLET_STATE_CLEAR_BLOCK_NOT_FOUND

    surviving_read = boundary.read_state(
        WalletStateReadPolicy(
            wallet_binding_id="wb-phase6-5-4-b",
            owner_user_id="user-2",
            requested_by_user_id="user-2",
            wallet_active=True,
        )
    )
    assert surviving_read.success is True
    assert surviving_read.state_snapshot == {
        "wallet_status": "ready",
        "available_balance": 50.0,
        "nonce": 9,
    }


def test_phase6_5_4_clear_state_blocks_invalid_contract() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.clear_state(
        WalletStateClearPolicy(
            wallet_binding_id="",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_CLEAR_BLOCK_INVALID_CONTRACT
    assert result.state_cleared is False
    assert result.cleared_revision is None
    assert result.notes == {"contract_error": "wallet_binding_id_required"}


def test_phase6_5_4_clear_state_blocks_ownership_mismatch() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-4-a",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        )
    )

    result = boundary.clear_state(
        WalletStateClearPolicy(
            wallet_binding_id="wb-phase6-5-4-a",
            owner_user_id="user-1",
            requested_by_user_id="user-99",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_CLEAR_BLOCK_OWNERSHIP_MISMATCH
    assert result.state_cleared is False
    assert result.cleared_revision is None


def test_phase6_5_4_clear_state_blocks_wallet_not_active() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-4-a",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        )
    )

    result = boundary.clear_state(
        WalletStateClearPolicy(
            wallet_binding_id="wb-phase6-5-4-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_CLEAR_BLOCK_WALLET_NOT_ACTIVE
    assert result.state_cleared is False
    assert result.cleared_revision is None


def test_phase6_5_4_clear_state_blocks_not_found() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.clear_state(_base_clear_policy())

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_CLEAR_BLOCK_NOT_FOUND
    assert result.state_cleared is False
    assert result.cleared_revision is None
