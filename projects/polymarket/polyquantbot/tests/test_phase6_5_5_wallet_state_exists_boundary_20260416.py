from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_EXISTS_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_EXISTS_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_EXISTS_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateExistsPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
)


def _base_exists_policy() -> WalletStateExistsPolicy:
    return WalletStateExistsPolicy(
        wallet_binding_id="wb-phase6-5-5-a",
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )


def test_phase6_5_5_has_state_returns_true_for_existing_named_wallet_binding() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-5-a",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        )
    )
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-5-b",
            owner_user_id="user-2",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 50.0, "nonce": 9},
        )
    )

    result = boundary.has_state(_base_exists_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.state_exists is True


def test_phase6_5_5_has_state_returns_false_when_named_wallet_binding_missing() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-5-other",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        )
    )

    result = boundary.has_state(_base_exists_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.state_exists is False


def test_phase6_5_5_has_state_blocks_invalid_contract() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.has_state(
        WalletStateExistsPolicy(
            wallet_binding_id="",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_EXISTS_BLOCK_INVALID_CONTRACT
    assert result.state_exists is False
    assert result.notes == {"contract_error": "wallet_binding_id_required"}


def test_phase6_5_5_has_state_blocks_ownership_mismatch() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-5-a",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        )
    )

    result = boundary.has_state(
        WalletStateExistsPolicy(
            wallet_binding_id="wb-phase6-5-5-a",
            owner_user_id="user-1",
            requested_by_user_id="user-99",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_EXISTS_BLOCK_OWNERSHIP_MISMATCH
    assert result.state_exists is False


def test_phase6_5_5_has_state_blocks_wallet_not_active() -> None:
    boundary = WalletStateStorageBoundary()
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id="wb-phase6-5-5-a",
            owner_user_id="user-1",
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": 100.0, "nonce": 1},
        )
    )

    result = boundary.has_state(
        WalletStateExistsPolicy(
            wallet_binding_id="wb-phase6-5-5-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_EXISTS_BLOCK_WALLET_NOT_ACTIVE
    assert result.state_exists is False
