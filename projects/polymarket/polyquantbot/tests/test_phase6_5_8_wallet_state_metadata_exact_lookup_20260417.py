from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_METADATA_EXACT_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_METADATA_EXACT_BLOCK_NOT_FOUND,
    WALLET_STATE_METADATA_EXACT_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_METADATA_EXACT_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateExactMetadataPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
)


def _store_state(
    *,
    boundary: WalletStateStorageBoundary,
    wallet_binding_id: str,
    owner_user_id: str = "user-1",
    nonce: int = 1,
) -> None:
    result = boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id=wallet_binding_id,
            owner_user_id=owner_user_id,
            wallet_active=True,
            state_snapshot={
                "wallet_status": "ready",
                "available_balance": 100.0,
                "nonce": nonce,
            },
        ),
    )
    assert result.success is True


def _base_exact_policy(wallet_binding_id: str = "wb-phase6-5-8-a") -> WalletStateExactMetadataPolicy:
    return WalletStateExactMetadataPolicy(
        wallet_binding_id=wallet_binding_id,
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )


def test_phase6_5_8_exact_metadata_lookup_success_metadata_only() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-8-a")
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-8-a", nonce=2)

    result = boundary.get_state_metadata(_base_exact_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.entry is not None
    assert result.entry.wallet_binding_id == "wb-phase6-5-8-a"
    assert result.entry.stored_revision == 2
    assert not hasattr(result.entry, "state_snapshot")


def test_phase6_5_8_exact_metadata_lookup_blocks_not_found() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.get_state_metadata(_base_exact_policy("missing-binding"))

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BLOCK_NOT_FOUND
    assert result.entry is None


def test_phase6_5_8_exact_metadata_lookup_blocks_invalid_contract() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.get_state_metadata(
        WalletStateExactMetadataPolicy(
            wallet_binding_id="",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BLOCK_INVALID_CONTRACT
    assert result.entry is None
    assert result.notes == {"contract_error": "wallet_binding_id_required"}


def test_phase6_5_8_exact_metadata_lookup_blocks_ownership_mismatch() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-8-a")

    result = boundary.get_state_metadata(
        WalletStateExactMetadataPolicy(
            wallet_binding_id="wb-phase6-5-8-a",
            owner_user_id="user-1",
            requested_by_user_id="user-2",
            wallet_active=True,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BLOCK_OWNERSHIP_MISMATCH
    assert result.entry is None


def test_phase6_5_8_exact_metadata_lookup_blocks_wallet_not_active() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-8-a")

    result = boundary.get_state_metadata(
        WalletStateExactMetadataPolicy(
            wallet_binding_id="wb-phase6-5-8-a",
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BLOCK_WALLET_NOT_ACTIVE
    assert result.entry is None
