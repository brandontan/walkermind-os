from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Any

WALLET_SECRET_LOAD_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_SECRET_LOAD_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_SECRET_LOAD_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_SECRET_LOAD_BLOCK_SECRET_MISSING = "secret_missing"
WALLET_SECRET_LOAD_BLOCK_RUNTIME_ERROR = "runtime_error"
WALLET_STATE_STORAGE_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_STORAGE_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_STORAGE_BLOCK_INVALID_STATE = "invalid_state"
WALLET_STATE_READ_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_READ_BLOCK_NOT_FOUND = "not_found"
WALLET_STATE_CLEAR_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_CLEAR_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_CLEAR_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_CLEAR_BLOCK_NOT_FOUND = "not_found"
WALLET_STATE_EXISTS_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_EXISTS_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_EXISTS_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_LIST_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_LIST_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_METADATA_EXACT_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_METADATA_EXACT_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_METADATA_EXACT_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_METADATA_EXACT_BLOCK_NOT_FOUND = "not_found"
WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_TOO_MANY = "wallet_binding_ids_too_many"
WALLET_STATE_METADATA_EXACT_BATCH_MAX_SIZE = 100
WALLET_STATE_READ_BATCH_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_READ_BATCH_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_READ_BATCH_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_READ_BATCH_BLOCK_TOO_MANY = "wallet_binding_ids_too_many"
WALLET_STATE_READ_BATCH_MAX_SIZE = 100


@dataclass(frozen=True)
class WalletSecretLoadPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    secret_env_var: str


@dataclass(frozen=True)
class WalletSecretLoadResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    secret_loaded: bool
    secret_fingerprint: str | None
    notes: dict[str, Any] | None = None


class WalletSecretLoader:
    """Phase 6.5.1 narrow wallet lifecycle foundation: secret loading contract only."""

    def load_secret(self, policy: WalletSecretLoadPolicy) -> WalletSecretLoadResult:
        contract_error = _validate_policy(policy)
        if contract_error is not None:
            return _blocked_result(
                policy=policy,
                blocked_reason=WALLET_SECRET_LOAD_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_result(
                policy=policy,
                blocked_reason=WALLET_SECRET_LOAD_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_result(
                policy=policy,
                blocked_reason=WALLET_SECRET_LOAD_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        try:
            secret_value = os.environ.get(policy.secret_env_var, "")
            if not secret_value:
                return _blocked_result(
                    policy=policy,
                    blocked_reason=WALLET_SECRET_LOAD_BLOCK_SECRET_MISSING,
                    notes={"secret_env_var": policy.secret_env_var},
                )

            return WalletSecretLoadResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                secret_loaded=True,
                secret_fingerprint=_secret_fingerprint(secret_value),
                notes={"secret_env_var": policy.secret_env_var},
            )
        except Exception as exc:  # explicit, deterministic block with no silent failure
            return _blocked_result(
                policy=policy,
                blocked_reason=WALLET_SECRET_LOAD_BLOCK_RUNTIME_ERROR,
                notes={"error_type": type(exc).__name__},
            )


def _validate_policy(policy: WalletSecretLoadPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if not isinstance(policy.secret_env_var, str) or not policy.secret_env_var.strip():
        return "secret_env_var_required"
    return None


def _blocked_result(
    *,
    policy: WalletSecretLoadPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletSecretLoadResult:
    return WalletSecretLoadResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        secret_loaded=False,
        secret_fingerprint=None,
        notes=notes,
    )


def _secret_fingerprint(secret_value: str) -> str:
    return hashlib.sha256(secret_value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class WalletStateReadPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool


@dataclass(frozen=True)
class WalletStateReadResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    state_found: bool
    state_snapshot: dict[str, Any] | None
    stored_revision: int | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletStateClearPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool


@dataclass(frozen=True)
class WalletStateClearResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    state_cleared: bool
    cleared_revision: int | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletStateExistsPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool


@dataclass(frozen=True)
class WalletStateExistsResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    state_exists: bool
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletStateMetadataEntry:
    wallet_binding_id: str
    stored_revision: int


@dataclass(frozen=True)
class WalletStateListMetadataPolicy:
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    wallet_binding_prefix: str | None = None
    min_stored_revision: int | None = None
    max_entries: int | None = None


@dataclass(frozen=True)
class WalletStateListMetadataResult:
    success: bool
    blocked_reason: str | None
    owner_user_id: str
    entries: list[WalletStateMetadataEntry] | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletStateExactMetadataPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool


@dataclass(frozen=True)
class WalletStateExactMetadataResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    entry: WalletStateMetadataEntry | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletStateExactBatchMetadataPolicy:
    wallet_binding_ids: list[str]
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool


@dataclass(frozen=True)
class WalletStateExactBatchMetadataEntry:
    wallet_binding_id: str
    stored_revision: int | None


@dataclass(frozen=True)
class WalletStateExactBatchMetadataResult:
    success: bool
    blocked_reason: str | None
    owner_user_id: str
    entries: list[WalletStateExactBatchMetadataEntry] | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletStateReadBatchPolicy:
    wallet_binding_ids: list[str]
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool


@dataclass(frozen=True)
class WalletStateReadBatchEntry:
    wallet_binding_id: str
    state_found: bool
    state_snapshot: dict[str, Any] | None
    stored_revision: int | None


@dataclass(frozen=True)
class WalletStateReadBatchResult:
    success: bool
    blocked_reason: str | None
    owner_user_id: str
    entries: list[WalletStateReadBatchEntry] | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletStateStoragePolicy:
    wallet_binding_id: str
    owner_user_id: str
    wallet_active: bool
    state_snapshot: dict[str, Any]


@dataclass(frozen=True)
class WalletStateStorageResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    state_stored: bool
    stored_revision: int | None
    notes: dict[str, Any] | None = None


class WalletStateStorageBoundary:
    """Phase 6.5.2 narrow wallet lifecycle boundary: wallet state/storage contract only."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def store_state(self, policy: WalletStateStoragePolicy) -> WalletStateStorageResult:
        contract_error = _validate_state_storage_policy(policy)
        if contract_error is not None:
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.wallet_active is not True:
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        state_error = _validate_state_snapshot(policy.state_snapshot)
        if state_error is not None:
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_INVALID_STATE,
                notes={"state_error": state_error},
            )

        prior_record = self._store.get(policy.wallet_binding_id)
        next_revision = 1 if prior_record is None else int(prior_record["revision"]) + 1
        self._store[policy.wallet_binding_id] = {
            "revision": next_revision,
            "owner_user_id": policy.owner_user_id,
            "state_snapshot": dict(policy.state_snapshot),
        }

        return WalletStateStorageResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            state_stored=True,
            stored_revision=next_revision,
            notes={"stored_keys": sorted(policy.state_snapshot.keys())},
        )

    def read_state(self, policy: WalletStateReadPolicy) -> WalletStateReadResult:
        """Phase 6.5.3 narrow wallet lifecycle boundary: read stored wallet state only."""
        contract_error = _validate_state_read_policy(policy)
        if contract_error is not None:
            return _blocked_state_read_result(
                policy=policy,
                blocked_reason=WALLET_STATE_READ_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_read_result(
                policy=policy,
                blocked_reason=WALLET_STATE_READ_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_read_result(
                policy=policy,
                blocked_reason=WALLET_STATE_READ_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        record = self._store.get(policy.wallet_binding_id)
        if record is None:
            return _blocked_state_read_result(
                policy=policy,
                blocked_reason=WALLET_STATE_READ_BLOCK_NOT_FOUND,
                notes={"wallet_binding_id": policy.wallet_binding_id},
            )

        return WalletStateReadResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            state_found=True,
            state_snapshot=dict(record["state_snapshot"]),
            stored_revision=int(record["revision"]),
            notes={"stored_keys": sorted(record["state_snapshot"].keys())},
        )

    def clear_state(self, policy: WalletStateClearPolicy) -> WalletStateClearResult:
        """Phase 6.5.4 narrow wallet lifecycle boundary: clear one stored wallet state only."""
        contract_error = _validate_state_clear_policy(policy)
        if contract_error is not None:
            return _blocked_state_clear_result(
                policy=policy,
                blocked_reason=WALLET_STATE_CLEAR_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_clear_result(
                policy=policy,
                blocked_reason=WALLET_STATE_CLEAR_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_clear_result(
                policy=policy,
                blocked_reason=WALLET_STATE_CLEAR_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        record = self._store.get(policy.wallet_binding_id)
        if record is None:
            return _blocked_state_clear_result(
                policy=policy,
                blocked_reason=WALLET_STATE_CLEAR_BLOCK_NOT_FOUND,
                notes={"wallet_binding_id": policy.wallet_binding_id},
            )

        cleared_revision = int(record["revision"])
        del self._store[policy.wallet_binding_id]
        return WalletStateClearResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            state_cleared=True,
            cleared_revision=cleared_revision,
            notes={"cleared": True},
        )

    def has_state(self, policy: WalletStateExistsPolicy) -> WalletStateExistsResult:
        """Phase 6.5.5 narrow wallet lifecycle boundary: check if one wallet state exists."""
        contract_error = _validate_state_exists_policy(policy)
        if contract_error is not None:
            return _blocked_state_exists_result(
                policy=policy,
                blocked_reason=WALLET_STATE_EXISTS_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_exists_result(
                policy=policy,
                blocked_reason=WALLET_STATE_EXISTS_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_exists_result(
                policy=policy,
                blocked_reason=WALLET_STATE_EXISTS_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        return WalletStateExistsResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            state_exists=policy.wallet_binding_id in self._store,
            notes={"wallet_binding_id": policy.wallet_binding_id},
        )

    def list_state_metadata(self, policy: WalletStateListMetadataPolicy) -> WalletStateListMetadataResult:
        """Phase 6.5.6 narrow wallet lifecycle boundary: list wallet state metadata for the named owner scope.
        Access requires owner identity match at policy level (requested_by_user_id must equal owner_user_id).
        Returns only entries whose stored owner_user_id matches policy.owner_user_id,
        sorted by wallet_binding_id ascending. No full state snapshot is exposed."""
        contract_error = _validate_state_list_metadata_policy(policy)
        if contract_error is not None:
            return _blocked_state_list_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_LIST_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_list_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_LIST_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_list_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_LIST_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        entries: list[WalletStateMetadataEntry] = []
        for wallet_binding_id, record in sorted(self._store.items()):
            if record.get("owner_user_id") != policy.owner_user_id:
                continue
            if (
                policy.wallet_binding_prefix is not None
                and not wallet_binding_id.startswith(policy.wallet_binding_prefix)
            ):
                continue
            stored_revision = int(record["revision"])
            if (
                policy.min_stored_revision is not None
                and stored_revision < policy.min_stored_revision
            ):
                continue
            entries.append(
                WalletStateMetadataEntry(
                    wallet_binding_id=wallet_binding_id,
                    stored_revision=stored_revision,
                ),
            )

        if policy.max_entries is not None:
            entries = entries[: policy.max_entries]

        applied_filters: dict[str, Any] = {}
        if policy.wallet_binding_prefix is not None:
            applied_filters["wallet_binding_prefix"] = policy.wallet_binding_prefix
        if policy.min_stored_revision is not None:
            applied_filters["min_stored_revision"] = policy.min_stored_revision
        if policy.max_entries is not None:
            applied_filters["max_entries"] = policy.max_entries

        notes: dict[str, Any] = {"entry_count": len(entries)}
        if applied_filters:
            notes["applied_filters"] = applied_filters

        return WalletStateListMetadataResult(
            success=True,
            blocked_reason=None,
            owner_user_id=policy.owner_user_id,
            entries=entries,
            notes=notes,
        )

    def get_state_metadata(self, policy: WalletStateExactMetadataPolicy) -> WalletStateExactMetadataResult:
        """Phase 6.5.8 narrow wallet lifecycle boundary: fetch one wallet metadata entry only."""
        contract_error = _validate_state_exact_metadata_policy(policy)
        if contract_error is not None:
            return _blocked_state_exact_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_METADATA_EXACT_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_exact_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_METADATA_EXACT_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_exact_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_METADATA_EXACT_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        record = self._store.get(policy.wallet_binding_id)
        if record is None or record.get("owner_user_id") != policy.owner_user_id:
            return _blocked_state_exact_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_METADATA_EXACT_BLOCK_NOT_FOUND,
                notes={"wallet_binding_id": policy.wallet_binding_id},
            )

        return WalletStateExactMetadataResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            entry=WalletStateMetadataEntry(
                wallet_binding_id=policy.wallet_binding_id,
                stored_revision=int(record["revision"]),
            ),
            notes={"wallet_binding_id": policy.wallet_binding_id},
        )

    def get_state_metadata_batch(
        self,
        policy: WalletStateExactBatchMetadataPolicy,
    ) -> WalletStateExactBatchMetadataResult:
        """Phase 6.5.9 narrow wallet lifecycle boundary: fetch metadata for explicit wallet_binding_ids.
        Deterministic ordering is preserved by iterating wallet_binding_ids in the exact input order.
        Output remains metadata-only (wallet_binding_id + stored_revision) and never exposes snapshots."""
        contract_error = _validate_state_exact_batch_metadata_policy(policy)
        if contract_error is not None:
            blocked_reason = WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_INVALID_CONTRACT
            if contract_error == WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_TOO_MANY:
                blocked_reason = WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_TOO_MANY
            return _blocked_state_exact_batch_metadata_result(
                policy=policy,
                blocked_reason=blocked_reason,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_exact_batch_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_exact_batch_metadata_result(
                policy=policy,
                blocked_reason=WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        entries: list[WalletStateExactBatchMetadataEntry] = []
        missing_wallet_binding_ids: list[str] = []
        for wallet_binding_id in policy.wallet_binding_ids:
            record = self._store.get(wallet_binding_id)
            if record is None or record.get("owner_user_id") != policy.owner_user_id:
                entries.append(
                    WalletStateExactBatchMetadataEntry(
                        wallet_binding_id=wallet_binding_id,
                        stored_revision=None,
                    ),
                )
                missing_wallet_binding_ids.append(wallet_binding_id)
                continue

            entries.append(
                WalletStateExactBatchMetadataEntry(
                    wallet_binding_id=wallet_binding_id,
                    stored_revision=int(record["revision"]),
                ),
            )

        return WalletStateExactBatchMetadataResult(
            success=True,
            blocked_reason=None,
            owner_user_id=policy.owner_user_id,
            entries=entries,
            notes={
                "entry_count": len(entries),
                "missing_wallet_binding_ids": missing_wallet_binding_ids,
            },
        )

    def read_state_batch(
        self,
        policy: WalletStateReadBatchPolicy,
    ) -> WalletStateReadBatchResult:
        """Phase 6.5.10 narrow wallet lifecycle boundary: fetch full state for explicit wallet_binding_ids.
        Deterministic ordering is preserved by iterating wallet_binding_ids in the exact input order.
        Missing or owner-mismatch entries return state_found=False with state_snapshot=None and stored_revision=None."""
        contract_error = _validate_state_read_batch_policy(policy)
        if contract_error is not None:
            blocked_reason = WALLET_STATE_READ_BATCH_BLOCK_INVALID_CONTRACT
            if contract_error == WALLET_STATE_READ_BATCH_BLOCK_TOO_MANY:
                blocked_reason = WALLET_STATE_READ_BATCH_BLOCK_TOO_MANY
            return _blocked_state_read_batch_result(
                policy=policy,
                blocked_reason=blocked_reason,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_read_batch_result(
                policy=policy,
                blocked_reason=WALLET_STATE_READ_BATCH_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_read_batch_result(
                policy=policy,
                blocked_reason=WALLET_STATE_READ_BATCH_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        entries: list[WalletStateReadBatchEntry] = []
        missing_wallet_binding_ids: list[str] = []
        for wallet_binding_id in policy.wallet_binding_ids:
            record = self._store.get(wallet_binding_id)
            if record is None or record.get("owner_user_id") != policy.owner_user_id:
                entries.append(
                    WalletStateReadBatchEntry(
                        wallet_binding_id=wallet_binding_id,
                        state_found=False,
                        state_snapshot=None,
                        stored_revision=None,
                    ),
                )
                missing_wallet_binding_ids.append(wallet_binding_id)
                continue

            entries.append(
                WalletStateReadBatchEntry(
                    wallet_binding_id=wallet_binding_id,
                    state_found=True,
                    state_snapshot=dict(record["state_snapshot"]),
                    stored_revision=int(record["revision"]),
                ),
            )

        return WalletStateReadBatchResult(
            success=True,
            blocked_reason=None,
            owner_user_id=policy.owner_user_id,
            entries=entries,
            notes={
                "entry_count": len(entries),
                "missing_wallet_binding_ids": missing_wallet_binding_ids,
            },
        )


def _validate_state_storage_policy(policy: WalletStateStoragePolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if not isinstance(policy.state_snapshot, dict):
        return "state_snapshot_must_be_dict"
    return None


def _validate_state_snapshot(state_snapshot: dict[str, Any]) -> str | None:
    required_fields = ("wallet_status", "available_balance", "nonce")
    for field in required_fields:
        if field not in state_snapshot:
            return f"{field}_required"

    wallet_status = state_snapshot["wallet_status"]
    if wallet_status not in {"ready", "suspended"}:
        return "wallet_status_invalid"

    available_balance = state_snapshot["available_balance"]
    if isinstance(available_balance, bool):
        return "available_balance_invalid_type"
    if not isinstance(available_balance, (int, float)):
        return "available_balance_invalid_type"
    if math.isnan(float(available_balance)):
        return "available_balance_nan"
    if available_balance < 0:
        return "available_balance_negative"

    nonce = state_snapshot["nonce"]
    if isinstance(nonce, bool):
        return "nonce_invalid"
    if not isinstance(nonce, int) or nonce < 0:
        return "nonce_invalid"
    return None


def _blocked_state_storage_result(
    *,
    policy: WalletStateStoragePolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateStorageResult:
    return WalletStateStorageResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        state_stored=False,
        stored_revision=None,
        notes=notes,
    )


def _validate_state_clear_policy(policy: WalletStateClearPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    return None


def _blocked_state_clear_result(
    *,
    policy: WalletStateClearPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateClearResult:
    return WalletStateClearResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        state_cleared=False,
        cleared_revision=None,
        notes=notes,
    )


def _validate_state_read_policy(policy: WalletStateReadPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    return None


def _validate_state_exists_policy(policy: WalletStateExistsPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    return None


def _blocked_state_read_result(
    *,
    policy: WalletStateReadPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateReadResult:
    return WalletStateReadResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        state_found=False,
        state_snapshot=None,
        stored_revision=None,
        notes=notes,
    )


def _blocked_state_exists_result(
    *,
    policy: WalletStateExistsPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateExistsResult:
    return WalletStateExistsResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        state_exists=False,
        notes=notes,
    )


def _validate_state_list_metadata_policy(policy: WalletStateListMetadataPolicy) -> str | None:
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if policy.wallet_binding_prefix is not None:
        if not isinstance(policy.wallet_binding_prefix, str):
            return "wallet_binding_prefix_must_be_str_or_none"
        if not policy.wallet_binding_prefix.strip():
            return "wallet_binding_prefix_required_when_provided"
    if policy.min_stored_revision is not None:
        if isinstance(policy.min_stored_revision, bool) or not isinstance(policy.min_stored_revision, int):
            return "min_stored_revision_must_be_int_or_none"
        if policy.min_stored_revision < 1:
            return "min_stored_revision_must_be_positive"
    if policy.max_entries is not None:
        if isinstance(policy.max_entries, bool) or not isinstance(policy.max_entries, int):
            return "max_entries_must_be_int_or_none"
        if policy.max_entries < 1:
            return "max_entries_must_be_positive"
    return None


def _validate_state_exact_metadata_policy(policy: WalletStateExactMetadataPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    return None


def _validate_state_exact_batch_metadata_policy(policy: WalletStateExactBatchMetadataPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_ids, list):
        return "wallet_binding_ids_must_be_list"
    if len(policy.wallet_binding_ids) == 0:
        return "wallet_binding_ids_required"
    if len(policy.wallet_binding_ids) > WALLET_STATE_METADATA_EXACT_BATCH_MAX_SIZE:
        return "wallet_binding_ids_too_many"
    for wallet_binding_id in policy.wallet_binding_ids:
        if not isinstance(wallet_binding_id, str) or not wallet_binding_id.strip():
            return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    return None


def _blocked_state_list_metadata_result(
    *,
    policy: WalletStateListMetadataPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateListMetadataResult:
    return WalletStateListMetadataResult(
        success=False,
        blocked_reason=blocked_reason,
        owner_user_id=policy.owner_user_id,
        entries=None,
        notes=notes,
    )


def _blocked_state_exact_metadata_result(
    *,
    policy: WalletStateExactMetadataPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateExactMetadataResult:
    return WalletStateExactMetadataResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        entry=None,
        notes=notes,
    )


def _blocked_state_exact_batch_metadata_result(
    *,
    policy: WalletStateExactBatchMetadataPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateExactBatchMetadataResult:
    entries: list[WalletStateExactBatchMetadataEntry] | None = None
    if blocked_reason == WALLET_STATE_METADATA_EXACT_BATCH_BLOCK_TOO_MANY:
        entries = []
    return WalletStateExactBatchMetadataResult(
        success=False,
        blocked_reason=blocked_reason,
        owner_user_id=policy.owner_user_id,
        entries=entries,
        notes=notes,
    )


def _validate_state_read_batch_policy(policy: WalletStateReadBatchPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_ids, list):
        return "wallet_binding_ids_must_be_list"
    if len(policy.wallet_binding_ids) == 0:
        return "wallet_binding_ids_required"
    if len(policy.wallet_binding_ids) > WALLET_STATE_READ_BATCH_MAX_SIZE:
        return WALLET_STATE_READ_BATCH_BLOCK_TOO_MANY
    for wallet_binding_id in policy.wallet_binding_ids:
        if not isinstance(wallet_binding_id, str) or not wallet_binding_id.strip():
            return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    return None


def _blocked_state_read_batch_result(
    *,
    policy: WalletStateReadBatchPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletStateReadBatchResult:
    entries: list[WalletStateReadBatchEntry] | None = None
    if blocked_reason == WALLET_STATE_READ_BATCH_BLOCK_TOO_MANY:
        entries = []
    return WalletStateReadBatchResult(
        success=False,
        blocked_reason=blocked_reason,
        owner_user_id=policy.owner_user_id,
        entries=entries,
        notes=notes,
    )
