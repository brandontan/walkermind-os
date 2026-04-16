from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_LIST_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_LIST_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateListMetadataPolicy,
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


def test_phase6_5_7_metadata_query_applies_prefix_revision_and_limit_deterministically() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="alpha-1")
    _store_state(boundary=boundary, wallet_binding_id="alpha-2")
    _store_state(boundary=boundary, wallet_binding_id="alpha-2", nonce=2)
    _store_state(boundary=boundary, wallet_binding_id="alpha-3")
    _store_state(boundary=boundary, wallet_binding_id="beta-1")

    result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            wallet_binding_prefix="alpha-",
            min_stored_revision=2,
            max_entries=2,
        ),
    )

    assert result.success is True
    assert result.blocked_reason is None
    assert result.entries is not None
    assert [entry.wallet_binding_id for entry in result.entries] == ["alpha-2"]
    assert [entry.stored_revision for entry in result.entries] == [2]
    assert result.notes == {
        "entry_count": 1,
        "applied_filters": {
            "wallet_binding_prefix": "alpha-",
            "min_stored_revision": 2,
            "max_entries": 2,
        },
    }
    assert not hasattr(result.entries[0], "state_snapshot")


def test_phase6_5_7_metadata_query_limit_respects_sorted_order() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="z-wallet")
    _store_state(boundary=boundary, wallet_binding_id="a-wallet")
    _store_state(boundary=boundary, wallet_binding_id="m-wallet")

    result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            max_entries=2,
        ),
    )

    assert result.success is True
    assert result.entries is not None
    assert [entry.wallet_binding_id for entry in result.entries] == [
        "a-wallet",
        "m-wallet",
    ]


def test_phase6_5_7_metadata_query_blocks_invalid_contract_for_filter_types() -> None:
    boundary = WalletStateStorageBoundary()

    invalid_prefix = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            wallet_binding_prefix="",
        ),
    )
    assert invalid_prefix.success is False
    assert invalid_prefix.blocked_reason == WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT
    assert invalid_prefix.notes == {"contract_error": "wallet_binding_prefix_required_when_provided"}

    invalid_min_revision = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            min_stored_revision=0,
        ),
    )
    assert invalid_min_revision.success is False
    assert invalid_min_revision.blocked_reason == WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT
    assert invalid_min_revision.notes == {"contract_error": "min_stored_revision_must_be_positive"}

    invalid_max_entries = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=True,
            max_entries=False,
        ),
    )
    assert invalid_max_entries.success is False
    assert invalid_max_entries.blocked_reason == WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT
    assert invalid_max_entries.notes == {"contract_error": "max_entries_must_be_int_or_none"}


def test_phase6_5_7_metadata_query_blocks_ownership_mismatch_and_inactive_wallet() -> None:
    boundary = WalletStateStorageBoundary()
    _store_state(boundary=boundary, wallet_binding_id="alpha-1")

    ownership_result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-2",
            wallet_active=True,
            wallet_binding_prefix="alpha-",
        ),
    )
    assert ownership_result.success is False
    assert ownership_result.blocked_reason == WALLET_STATE_LIST_BLOCK_OWNERSHIP_MISMATCH

    inactive_result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
            wallet_binding_prefix="alpha-",
        ),
    )
    assert inactive_result.success is False
    assert inactive_result.blocked_reason == WALLET_STATE_LIST_BLOCK_WALLET_NOT_ACTIVE
