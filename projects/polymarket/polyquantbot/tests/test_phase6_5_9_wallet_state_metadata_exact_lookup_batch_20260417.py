from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_TOO_MANY,
    WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateExactBatchMetadataPolicy,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
    _validate_state_exact_batch_metadata_policy,
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


def _base_batch_policy(
    wallet_binding_ids: list[str] | None = None,
) -> WalletStateExactBatchMetadataPolicy:
    return WalletStateExactBatchMetadataPolicy(
        wallet_binding_ids=wallet_binding_ids or ["wb-phase6-5-9-a", "wb-phase6-5-9-b"],
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )


def test_phase6_5_9_exact_metadata_batch_success_preserves_input_order_and_metadata_only() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-9-a")
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-9-a", nonce=2)
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-9-b")

    result = boundary.get_state_metadata_batch(_base_batch_policy(["wb-phase6-5-9-b", "wb-phase6-5-9-a"]))

    assert result.success is True
    assert result.blocked_reason is None
    assert result.entries is not None
    assert [entry.wallet_binding_id for entry in result.entries] == ["wb-phase6-5-9-b", "wb-phase6-5-9-a"]
    assert [entry.stored_revision for entry in result.entries] == [1, 2]
    assert not hasattr(result.entries[0], "state_snapshot")


def test_phase6_5_9_exact_metadata_batch_missing_entries_are_deterministic() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-9-a")
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-9-other-owner", owner_user_id="user-2")

    result = boundary.get_state_metadata_batch(
        _base_batch_policy(
            [
                "wb-phase6-5-9-a",
                "wb-phase6-5-9-missing",
                "wb-phase6-5-9-other-owner",
            ],
        ),
    )

    assert result.success is True
    assert result.entries is not None
    assert [entry.wallet_binding_id for entry in result.entries] == [
        "wb-phase6-5-9-a",
        "wb-phase6-5-9-missing",
        "wb-phase6-5-9-other-owner",
    ]
    assert [entry.stored_revision for entry in result.entries] == [1, None, None]
    assert result.notes == {
        "entry_count": 3,
        "missing_wallet_binding_ids": [
            "wb-phase6-5-9-missing",
            "wb-phase6-5-9-other-owner",
        ],
    }


def test_phase6_5_9_exact_metadata_batch_blocks_invalid_contract() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.get_state_metadata_batch(
        WalletStateExactBatchMetadataPolicy(
            wallet_binding_ids=[],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_INVALID_CONTRACT
    assert result.entries is None
    assert result.notes == {"contract_error": "wallet_binding_ids_required"}


def test_phase6_5_9_exact_metadata_batch_blocks_ownership_mismatch() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-9-a")

    result = boundary.get_state_metadata_batch(
        WalletStateExactBatchMetadataPolicy(
            wallet_binding_ids=["wb-phase6-5-9-a"],
            owner_user_id="user-1",
            requested_by_user_id="user-2",
            wallet_active=True,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_OWNERSHIP_MISMATCH
    assert result.entries is None


def test_phase6_5_9_exact_metadata_batch_blocks_wallet_not_active() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="wb-phase6-5-9-a")

    result = boundary.get_state_metadata_batch(
        WalletStateExactBatchMetadataPolicy(
            wallet_binding_ids=["wb-phase6-5-9-a"],
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
        ),
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_WALLET_NOT_ACTIVE
    assert result.entries is None


def test_phase6_5_9_exact_metadata_batch_blocks_too_many_wallet_binding_ids() -> None:
    boundary = WalletStateStorageBoundary()
    wallet_binding_ids = [f"wb-phase6-5-9-{index}" for index in range(101)]
    policy = WalletStateExactBatchMetadataPolicy(
        wallet_binding_ids=wallet_binding_ids,
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )

    assert _validate_state_exact_batch_metadata_policy(policy) == "wallet_binding_ids_too_many"

    result = boundary.get_state_metadata_batch(policy)

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_TOO_MANY
    assert result.entries == []
    assert result.owner_user_id == "user-1"
