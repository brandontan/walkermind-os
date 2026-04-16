from __future__ import annotations

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT,
    WALLET_STATE_LIST_BLOCK_OWNERSHIP_MISMATCH,
    WALLET_STATE_LIST_BLOCK_WALLET_NOT_ACTIVE,
    WalletStateListMetadataPolicy,
    WalletStateMetadataEntry,
    WalletStateStorageBoundary,
    WalletStateStoragePolicy,
)


def _base_list_policy() -> WalletStateListMetadataPolicy:
    return WalletStateListMetadataPolicy(
        owner_user_id="user-1",
        requested_by_user_id="user-1",
        wallet_active=True,
    )


def _store_entry(
    boundary: WalletStateStorageBoundary,
    wallet_binding_id: str,
    owner_user_id: str = "user-1",
    available_balance: float = 100.0,
    nonce: int = 1,
) -> None:
    boundary.store_state(
        WalletStateStoragePolicy(
            wallet_binding_id=wallet_binding_id,
            owner_user_id=owner_user_id,
            wallet_active=True,
            state_snapshot={"wallet_status": "ready", "available_balance": available_balance, "nonce": nonce},
        )
    )


def test_phase6_5_6_list_state_metadata_empty_result() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.list_state_metadata(_base_list_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.owner_user_id == "user-1"
    assert result.entries == []
    assert result.notes == {"entry_count": 0}


def test_phase6_5_6_list_state_metadata_populated_result() -> None:
    boundary = WalletStateStorageBoundary()
    _store_entry(boundary, "wb-phase6-5-6-a")
    _store_entry(boundary, "wb-phase6-5-6-b")

    result = boundary.list_state_metadata(_base_list_policy())

    assert result.success is True
    assert result.blocked_reason is None
    assert result.owner_user_id == "user-1"
    assert result.entries is not None
    assert len(result.entries) == 2
    assert result.entries[0].wallet_binding_id == "wb-phase6-5-6-a"
    assert result.entries[0].stored_revision == 1
    assert result.entries[1].wallet_binding_id == "wb-phase6-5-6-b"
    assert result.entries[1].stored_revision == 1
    assert result.notes == {"entry_count": 2}


def test_phase6_5_6_list_state_metadata_returns_metadata_only_no_snapshot() -> None:
    boundary = WalletStateStorageBoundary()
    _store_entry(boundary, "wb-phase6-5-6-a")

    result = boundary.list_state_metadata(_base_list_policy())

    assert result.success is True
    assert result.entries is not None
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert isinstance(entry, WalletStateMetadataEntry)
    assert hasattr(entry, "wallet_binding_id")
    assert hasattr(entry, "stored_revision")
    assert not hasattr(entry, "state_snapshot")


def test_phase6_5_6_list_state_metadata_deterministic_ordering() -> None:
    boundary = WalletStateStorageBoundary()
    # Insert in reverse alphabetical order to verify sort is enforced regardless of insertion order
    _store_entry(boundary, "wb-phase6-5-6-z")
    _store_entry(boundary, "wb-phase6-5-6-m")
    _store_entry(boundary, "wb-phase6-5-6-a")

    result = boundary.list_state_metadata(_base_list_policy())

    assert result.success is True
    assert result.entries is not None
    assert len(result.entries) == 3
    binding_ids = [e.wallet_binding_id for e in result.entries]
    assert binding_ids == sorted(binding_ids)
    assert binding_ids == ["wb-phase6-5-6-a", "wb-phase6-5-6-m", "wb-phase6-5-6-z"]


def test_phase6_5_6_list_state_metadata_revision_reflects_stored_revision() -> None:
    boundary = WalletStateStorageBoundary()
    _store_entry(boundary, "wb-phase6-5-6-a", nonce=1)
    _store_entry(boundary, "wb-phase6-5-6-a", nonce=2)
    _store_entry(boundary, "wb-phase6-5-6-a", nonce=3)

    result = boundary.list_state_metadata(_base_list_policy())

    assert result.success is True
    assert result.entries is not None
    assert len(result.entries) == 1
    assert result.entries[0].stored_revision == 3


def test_phase6_5_6_list_state_metadata_blocks_invalid_contract_empty_owner() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="",
            requested_by_user_id="user-1",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT
    assert result.entries is None
    assert result.notes == {"contract_error": "owner_user_id_required"}


def test_phase6_5_6_list_state_metadata_blocks_invalid_contract_empty_requester() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT
    assert result.entries is None
    assert result.notes == {"contract_error": "requested_by_user_id_required"}


def test_phase6_5_6_list_state_metadata_blocks_invalid_contract_non_bool_active() -> None:
    boundary = WalletStateStorageBoundary()

    result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=1,  # type: ignore[arg-type]
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT
    assert result.entries is None
    assert result.notes == {"contract_error": "wallet_active_must_be_bool"}


def test_phase6_5_6_list_state_metadata_blocks_ownership_mismatch() -> None:
    boundary = WalletStateStorageBoundary()
    _store_entry(boundary, "wb-phase6-5-6-a")

    result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-99",
            wallet_active=True,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_LIST_BLOCK_OWNERSHIP_MISMATCH
    assert result.entries is None


def test_phase6_5_6_list_state_metadata_blocks_wallet_not_active() -> None:
    boundary = WalletStateStorageBoundary()
    _store_entry(boundary, "wb-phase6-5-6-a")

    result = boundary.list_state_metadata(
        WalletStateListMetadataPolicy(
            owner_user_id="user-1",
            requested_by_user_id="user-1",
            wallet_active=False,
        )
    )

    assert result.success is False
    assert result.blocked_reason == WALLET_STATE_LIST_BLOCK_WALLET_NOT_ACTIVE
    assert result.entries is None
