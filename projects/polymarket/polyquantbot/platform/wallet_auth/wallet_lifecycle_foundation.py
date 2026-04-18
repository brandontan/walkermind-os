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
WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_RECONCILIATION_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_RECONCILIATION_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_RECONCILIATION_OUTCOME_MATCH = "match"
WALLET_RECONCILIATION_OUTCOME_STATE_MISSING = "state_missing"
WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH = "revision_mismatch"
WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH = "snapshot_mismatch"
WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_RECONCILIATION_BATCH_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_RECONCILIATION_BATCH_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_RECONCILIATION_BATCH_BLOCK_TOO_MANY = "wallet_entries_too_many"
WALLET_RECONCILIATION_BATCH_MAX_SIZE = 100
WALLET_CORRECTION_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_CORRECTION_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_CORRECTION_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_CORRECTION_BLOCK_REVISION_CONFLICT = "revision_conflict"
WALLET_CORRECTION_BLOCK_PATH_STATE_MISSING = "correction_path_blocked_state_missing"
WALLET_CORRECTION_BLOCK_PATH_REVISION_MISMATCH = "correction_path_blocked_revision_mismatch"
WALLET_CORRECTION_BLOCK_INVALID_SNAPSHOT = "correction_snapshot_invalid"
WALLET_CORRECTION_RESULT_ACCEPTED = "correction_accepted"
WALLET_CORRECTION_RESULT_BLOCKED = "correction_blocked"
WALLET_CORRECTION_RESULT_PATH_BLOCKED = "correction_path_blocked"
WALLET_CORRECTION_RESULT_NOT_REQUIRED = "correction_not_required"
WALLET_RETRY_WORK_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_RETRY_WORK_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_RETRY_WORK_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_RETRY_WORK_BLOCK_NON_RETRYABLE_RESULT = "non_retryable_correction_result"
WALLET_RETRY_WORK_BLOCK_RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
WALLET_RETRY_WORK_DECISION_ACCEPTED = "retry_accepted"
WALLET_RETRY_WORK_DECISION_SKIPPED = "retry_skipped"
WALLET_RETRY_WORK_DECISION_BLOCKED = "retry_blocked"
WALLET_RETRY_WORK_DECISION_EXHAUSTED = "retry_exhausted"
WALLET_RETRY_WORKER_ACTION_RETRY = "retry"
WALLET_RETRY_WORKER_ACTION_SKIP = "skip"
WALLET_RETRY_WORK_MAX_BUDGET = 10
WALLET_PUBLIC_READINESS_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_PUBLIC_READINESS_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_PUBLIC_READINESS_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_PUBLIC_READINESS_BLOCK_STATE_READ_NOT_READY = "state_read_not_ready"
WALLET_PUBLIC_READINESS_BLOCK_RECONCILIATION_UNRESOLVED = "reconciliation_unresolved"
WALLET_PUBLIC_READINESS_RESULT_GO = "go"
WALLET_PUBLIC_READINESS_RESULT_HOLD = "hold"
WALLET_PUBLIC_READINESS_RESULT_BLOCKED = "blocked"


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


@dataclass(frozen=True)
class WalletReconciliationPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    expected_state_snapshot: dict[str, Any]
    expected_revision: int | None = None


@dataclass(frozen=True)
class WalletReconciliationResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    reconciliation_outcome: str | None
    stored_revision: int | None
    expected_revision: int | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletBatchReconciliationEntry:
    wallet_binding_id: str
    expected_state_snapshot: dict[str, Any]
    expected_revision: int | None = None


@dataclass(frozen=True)
class WalletBatchReconciliationPolicy:
    entries: list[WalletBatchReconciliationEntry]
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool


@dataclass(frozen=True)
class WalletBatchReconciliationResultEntry:
    wallet_binding_id: str
    reconciliation_outcome: str
    stored_revision: int | None
    expected_revision: int | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletBatchReconciliationResult:
    success: bool
    blocked_reason: str | None
    owner_user_id: str
    entries: list[WalletBatchReconciliationResultEntry] | None
    notes: dict[str, Any] | None = None


class WalletLifecycleReconciliationBoundary:
    """Phase 6.6.1 narrow reconciliation foundation: compare expected vs stored wallet lifecycle state.
    Read and evaluate only — no mutation, correction, retry, or automation."""

    def __init__(self, storage_boundary: WalletStateStorageBoundary) -> None:
        self._storage = storage_boundary

    def reconcile_wallet_state(
        self, policy: WalletReconciliationPolicy
    ) -> WalletReconciliationResult:
        contract_error = _validate_reconciliation_policy(policy)
        if contract_error is not None:
            return _blocked_reconciliation_result(
                policy=policy,
                blocked_reason=WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_reconciliation_result(
                policy=policy,
                blocked_reason=WALLET_RECONCILIATION_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_reconciliation_result(
                policy=policy,
                blocked_reason=WALLET_RECONCILIATION_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        batch_result = self._storage.read_state_batch(
            WalletStateReadBatchPolicy(
                wallet_binding_ids=[policy.wallet_binding_id],
                owner_user_id=policy.owner_user_id,
                requested_by_user_id=policy.requested_by_user_id,
                wallet_active=policy.wallet_active,
            )
        )

        if not batch_result.success or batch_result.entries is None:
            return _blocked_reconciliation_result(
                policy=policy,
                blocked_reason=WALLET_RECONCILIATION_BLOCK_INVALID_CONTRACT,
                notes={"storage_block": batch_result.blocked_reason},
            )

        entry = batch_result.entries[0]
        if not entry.state_found:
            return WalletReconciliationResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
                stored_revision=None,
                expected_revision=policy.expected_revision,
                notes={"wallet_binding_id": policy.wallet_binding_id},
            )

        stored_revision = entry.stored_revision
        stored_snapshot = entry.state_snapshot

        if (
            policy.expected_revision is not None
            and stored_revision != policy.expected_revision
        ):
            return WalletReconciliationResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
                stored_revision=stored_revision,
                expected_revision=policy.expected_revision,
                notes={
                    "stored_revision": stored_revision,
                    "expected_revision": policy.expected_revision,
                },
            )

        if stored_snapshot != policy.expected_state_snapshot:
            mismatched_keys = sorted(
                k
                for k in set(list(stored_snapshot.keys()) + list(policy.expected_state_snapshot.keys()))
                if stored_snapshot.get(k) != policy.expected_state_snapshot.get(k)
            )
            return WalletReconciliationResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
                stored_revision=stored_revision,
                expected_revision=policy.expected_revision,
                notes={"mismatch_keys": mismatched_keys},
            )

        return WalletReconciliationResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_MATCH,
            stored_revision=stored_revision,
            expected_revision=policy.expected_revision,
            notes={"stored_revision": stored_revision},
        )

    def reconcile_wallet_state_batch(
        self, policy: WalletBatchReconciliationPolicy
    ) -> WalletBatchReconciliationResult:
        """Phase 6.6.2 batch reconciliation: evaluate multiple expected wallet states against stored states.
        Deterministic per-entry outcomes in exact input order. Read and evaluate only — no mutation or correction."""
        contract_error = _validate_batch_reconciliation_policy(policy)
        if contract_error is not None:
            blocked_reason = WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT
            if contract_error == WALLET_RECONCILIATION_BATCH_BLOCK_TOO_MANY:
                blocked_reason = WALLET_RECONCILIATION_BATCH_BLOCK_TOO_MANY
            return _blocked_batch_reconciliation_result(
                policy=policy,
                blocked_reason=blocked_reason,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_batch_reconciliation_result(
                policy=policy,
                blocked_reason=WALLET_RECONCILIATION_BATCH_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_batch_reconciliation_result(
                policy=policy,
                blocked_reason=WALLET_RECONCILIATION_BATCH_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        wallet_binding_ids = [e.wallet_binding_id for e in policy.entries]
        batch_read = self._storage.read_state_batch(
            WalletStateReadBatchPolicy(
                wallet_binding_ids=wallet_binding_ids,
                owner_user_id=policy.owner_user_id,
                requested_by_user_id=policy.requested_by_user_id,
                wallet_active=policy.wallet_active,
            )
        )

        if not batch_read.success or batch_read.entries is None:
            return _blocked_batch_reconciliation_result(
                policy=policy,
                blocked_reason=WALLET_RECONCILIATION_BATCH_BLOCK_INVALID_CONTRACT,
                notes={"storage_block": batch_read.blocked_reason},
            )

        stored_by_id: dict[str, WalletStateReadBatchEntry] = {
            e.wallet_binding_id: e for e in batch_read.entries
        }

        result_entries: list[WalletBatchReconciliationResultEntry] = []
        outcome_counts: dict[str, int] = {
            WALLET_RECONCILIATION_OUTCOME_MATCH: 0,
            WALLET_RECONCILIATION_OUTCOME_STATE_MISSING: 0,
            WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH: 0,
            WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH: 0,
        }

        for entry in policy.entries:
            stored = stored_by_id.get(entry.wallet_binding_id)

            if stored is None or not stored.state_found:
                result_entries.append(
                    WalletBatchReconciliationResultEntry(
                        wallet_binding_id=entry.wallet_binding_id,
                        reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
                        stored_revision=None,
                        expected_revision=entry.expected_revision,
                        notes={"wallet_binding_id": entry.wallet_binding_id},
                    )
                )
                outcome_counts[WALLET_RECONCILIATION_OUTCOME_STATE_MISSING] += 1
                continue

            stored_revision = stored.stored_revision
            stored_snapshot = stored.state_snapshot

            if (
                entry.expected_revision is not None
                and stored_revision != entry.expected_revision
            ):
                result_entries.append(
                    WalletBatchReconciliationResultEntry(
                        wallet_binding_id=entry.wallet_binding_id,
                        reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
                        stored_revision=stored_revision,
                        expected_revision=entry.expected_revision,
                        notes={
                            "stored_revision": stored_revision,
                            "expected_revision": entry.expected_revision,
                        },
                    )
                )
                outcome_counts[WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH] += 1
                continue

            if stored_snapshot != entry.expected_state_snapshot:
                mismatched_keys = sorted(
                    k
                    for k in set(list(stored_snapshot.keys()) + list(entry.expected_state_snapshot.keys()))
                    if stored_snapshot.get(k) != entry.expected_state_snapshot.get(k)
                )
                result_entries.append(
                    WalletBatchReconciliationResultEntry(
                        wallet_binding_id=entry.wallet_binding_id,
                        reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
                        stored_revision=stored_revision,
                        expected_revision=entry.expected_revision,
                        notes={"mismatch_keys": mismatched_keys},
                    )
                )
                outcome_counts[WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH] += 1
                continue

            result_entries.append(
                WalletBatchReconciliationResultEntry(
                    wallet_binding_id=entry.wallet_binding_id,
                    reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_MATCH,
                    stored_revision=stored_revision,
                    expected_revision=entry.expected_revision,
                    notes={"stored_revision": stored_revision},
                )
            )
            outcome_counts[WALLET_RECONCILIATION_OUTCOME_MATCH] += 1

        return WalletBatchReconciliationResult(
            success=True,
            blocked_reason=None,
            owner_user_id=policy.owner_user_id,
            entries=result_entries,
            notes={
                "entry_count": len(result_entries),
                "outcome_counts": outcome_counts,
            },
        )


def _validate_reconciliation_policy(policy: WalletReconciliationPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if not isinstance(policy.expected_state_snapshot, dict):
        return "expected_state_snapshot_must_be_dict"
    if policy.expected_revision is not None:
        if isinstance(policy.expected_revision, bool) or not isinstance(policy.expected_revision, int):
            return "expected_revision_must_be_int_or_none"
        if policy.expected_revision < 1:
            return "expected_revision_must_be_positive"
    return None


def _blocked_reconciliation_result(
    *,
    policy: WalletReconciliationPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletReconciliationResult:
    return WalletReconciliationResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        reconciliation_outcome=None,
        stored_revision=None,
        expected_revision=policy.expected_revision if hasattr(policy, "expected_revision") else None,
        notes=notes,
    )


def _validate_batch_reconciliation_policy(policy: WalletBatchReconciliationPolicy) -> str | None:
    if not isinstance(policy.entries, list):
        return "entries_must_be_list"
    if len(policy.entries) == 0:
        return "entries_required"
    if len(policy.entries) > WALLET_RECONCILIATION_BATCH_MAX_SIZE:
        return WALLET_RECONCILIATION_BATCH_BLOCK_TOO_MANY
    for entry in policy.entries:
        if not isinstance(entry.wallet_binding_id, str) or not entry.wallet_binding_id.strip():
            return "wallet_binding_id_required"
        if not isinstance(entry.expected_state_snapshot, dict):
            return "expected_state_snapshot_must_be_dict"
        if entry.expected_revision is not None:
            if isinstance(entry.expected_revision, bool) or not isinstance(entry.expected_revision, int):
                return "expected_revision_must_be_int_or_none"
            if entry.expected_revision < 1:
                return "expected_revision_must_be_positive"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    return None


def _blocked_batch_reconciliation_result(
    *,
    policy: WalletBatchReconciliationPolicy,
    blocked_reason: str,
    notes: dict[str, Any] | None,
) -> WalletBatchReconciliationResult:
    return WalletBatchReconciliationResult(
        success=False,
        blocked_reason=blocked_reason,
        owner_user_id=policy.owner_user_id,
        entries=None,
        notes=notes,
    )


@dataclass(frozen=True)
class WalletCorrectionPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    reconciliation_outcome: str
    correction_snapshot: dict[str, Any]
    expected_stored_revision: int


@dataclass(frozen=True)
class WalletCorrectionResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    correction_result_category: str | None
    applied_revision: int | None
    notes: dict[str, Any] | None = None


_WALLET_CORRECTION_ALL_OUTCOMES: frozenset[str] = frozenset({
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
})
_WALLET_CORRECTION_PATH_BLOCKED_MAP: dict[str, str] = {
    WALLET_RECONCILIATION_OUTCOME_STATE_MISSING: WALLET_CORRECTION_BLOCK_PATH_STATE_MISSING,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH: WALLET_CORRECTION_BLOCK_PATH_REVISION_MISMATCH,
}


class WalletReconciliationCorrectionBoundary:
    """Phase 6.6.3 narrow reconciliation correction foundation:
    accept and evaluate owner-scoped correction requests derived from reconciliation outcomes.
    Manual/foundation only -- no scheduler, retry worker, or background automation."""

    def __init__(self, storage_boundary: WalletStateStorageBoundary) -> None:
        self._storage = storage_boundary

    def apply_correction(self, policy: WalletCorrectionPolicy) -> WalletCorrectionResult:
        contract_error = _validate_correction_policy(policy)
        if contract_error is not None:
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=WALLET_CORRECTION_BLOCK_INVALID_CONTRACT,
                correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=WALLET_CORRECTION_BLOCK_OWNERSHIP_MISMATCH,
                correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=WALLET_CORRECTION_BLOCK_WALLET_NOT_ACTIVE,
                correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
                notes={"wallet_active": False},
            )

        if policy.reconciliation_outcome == WALLET_RECONCILIATION_OUTCOME_MATCH:
            return WalletCorrectionResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                correction_result_category=WALLET_CORRECTION_RESULT_NOT_REQUIRED,
                applied_revision=None,
                notes={"reconciliation_outcome": policy.reconciliation_outcome},
            )

        path_block = _WALLET_CORRECTION_PATH_BLOCKED_MAP.get(policy.reconciliation_outcome)
        if path_block is not None:
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=path_block,
                correction_result_category=WALLET_CORRECTION_RESULT_PATH_BLOCKED,
                notes={"reconciliation_outcome": policy.reconciliation_outcome},
            )

        # snapshot_mismatch: correction allowed path -- verify optimistic lock via read
        read_batch = self._storage.read_state_batch(
            WalletStateReadBatchPolicy(
                wallet_binding_ids=[policy.wallet_binding_id],
                owner_user_id=policy.owner_user_id,
                requested_by_user_id=policy.requested_by_user_id,
                wallet_active=policy.wallet_active,
            )
        )

        if not read_batch.success or read_batch.entries is None:
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=WALLET_CORRECTION_BLOCK_REVISION_CONFLICT,
                correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
                notes={"storage_block": read_batch.blocked_reason},
            )

        stored_entry = read_batch.entries[0]
        if not stored_entry.state_found or stored_entry.stored_revision is None:
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=WALLET_CORRECTION_BLOCK_REVISION_CONFLICT,
                correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
                notes={"reason": "state_not_found_at_correction_time"},
            )

        if stored_entry.stored_revision != policy.expected_stored_revision:
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=WALLET_CORRECTION_BLOCK_REVISION_CONFLICT,
                correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
                notes={
                    "stored_revision": stored_entry.stored_revision,
                    "expected_stored_revision": policy.expected_stored_revision,
                },
            )

        store_result = self._storage.store_state(
            WalletStateStoragePolicy(
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                wallet_active=policy.wallet_active,
                state_snapshot=policy.correction_snapshot,
            )
        )

        if not store_result.success:
            block_reason = (
                WALLET_CORRECTION_BLOCK_INVALID_SNAPSHOT
                if store_result.blocked_reason == WALLET_STATE_STORAGE_BLOCK_INVALID_STATE
                else WALLET_CORRECTION_BLOCK_INVALID_CONTRACT
            )
            return _blocked_correction_result(
                policy=policy,
                blocked_reason=block_reason,
                correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
                notes={"store_block": store_result.blocked_reason},
            )

        return WalletCorrectionResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            correction_result_category=WALLET_CORRECTION_RESULT_ACCEPTED,
            applied_revision=store_result.stored_revision,
            notes={
                "reconciliation_outcome": policy.reconciliation_outcome,
                "applied_revision": store_result.stored_revision,
            },
        )


def _validate_correction_policy(policy: WalletCorrectionPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if (
        not isinstance(policy.reconciliation_outcome, str)
        or policy.reconciliation_outcome not in _WALLET_CORRECTION_ALL_OUTCOMES
    ):
        return "reconciliation_outcome_invalid"
    if not isinstance(policy.correction_snapshot, dict):
        return "correction_snapshot_must_be_dict"
    if isinstance(policy.expected_stored_revision, bool) or not isinstance(policy.expected_stored_revision, int):
        return "expected_stored_revision_must_be_int"
    if policy.expected_stored_revision < 1:
        return "expected_stored_revision_must_be_positive"
    return None


def _blocked_correction_result(
    *,
    policy: WalletCorrectionPolicy,
    blocked_reason: str,
    correction_result_category: str,
    notes: dict[str, Any] | None,
) -> WalletCorrectionResult:
    return WalletCorrectionResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        correction_result_category=correction_result_category,
        applied_revision=None,
        notes=notes,
    )


@dataclass(frozen=True)
class WalletReconciliationRetryWorkPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    correction_result_category: str
    correction_blocked_reason: str | None
    retry_attempt: int
    retry_budget: int
    worker_action: str


@dataclass(frozen=True)
class WalletReconciliationRetryWorkResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    retry_result_category: str
    accepted_for_retry: bool
    retry_attempt: int
    retry_budget: int
    next_retry_attempt: int | None
    notes: dict[str, Any] | None = None


_WALLET_RETRY_VALID_CORRECTION_RESULT_CATEGORIES: frozenset[str] = frozenset({
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_CORRECTION_RESULT_PATH_BLOCKED,
    WALLET_CORRECTION_RESULT_NOT_REQUIRED,
})
_WALLET_RETRY_RETRYABLE_CORRECTION_BLOCKS: frozenset[str] = frozenset({
    WALLET_CORRECTION_BLOCK_REVISION_CONFLICT,
})
_WALLET_RETRY_VALID_WORKER_ACTIONS: frozenset[str] = frozenset({
    WALLET_RETRY_WORKER_ACTION_RETRY,
    WALLET_RETRY_WORKER_ACTION_SKIP,
})


class WalletReconciliationRetryWorkerBoundary:
    """Phase 6.6.4 narrow reconciliation retry/worker foundation.
    Accept deterministic owner-scoped retry work items from correction outcomes.
    Foundation only: no scheduler daemon, no background orchestration mesh."""

    def decide_retry_work_item(
        self,
        policy: WalletReconciliationRetryWorkPolicy,
    ) -> WalletReconciliationRetryWorkResult:
        contract_error = _validate_retry_work_policy(policy)
        if contract_error is not None:
            return _blocked_retry_work_result(
                policy=policy,
                blocked_reason=WALLET_RETRY_WORK_BLOCK_INVALID_CONTRACT,
                retry_result_category=WALLET_RETRY_WORK_DECISION_BLOCKED,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_retry_work_result(
                policy=policy,
                blocked_reason=WALLET_RETRY_WORK_BLOCK_OWNERSHIP_MISMATCH,
                retry_result_category=WALLET_RETRY_WORK_DECISION_BLOCKED,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_retry_work_result(
                policy=policy,
                blocked_reason=WALLET_RETRY_WORK_BLOCK_WALLET_NOT_ACTIVE,
                retry_result_category=WALLET_RETRY_WORK_DECISION_BLOCKED,
                notes={"wallet_active": False},
            )

        if policy.worker_action == WALLET_RETRY_WORKER_ACTION_SKIP:
            return WalletReconciliationRetryWorkResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                retry_result_category=WALLET_RETRY_WORK_DECISION_SKIPPED,
                accepted_for_retry=False,
                retry_attempt=policy.retry_attempt,
                retry_budget=policy.retry_budget,
                next_retry_attempt=None,
                notes={"worker_action": policy.worker_action},
            )

        if not _is_retryable_correction_path(policy):
            return _blocked_retry_work_result(
                policy=policy,
                blocked_reason=WALLET_RETRY_WORK_BLOCK_NON_RETRYABLE_RESULT,
                retry_result_category=WALLET_RETRY_WORK_DECISION_BLOCKED,
                notes={
                    "correction_result_category": policy.correction_result_category,
                    "correction_blocked_reason": policy.correction_blocked_reason,
                },
            )

        if policy.retry_attempt > policy.retry_budget:
            return _blocked_retry_work_result(
                policy=policy,
                blocked_reason=WALLET_RETRY_WORK_BLOCK_RETRY_BUDGET_EXHAUSTED,
                retry_result_category=WALLET_RETRY_WORK_DECISION_EXHAUSTED,
                notes={
                    "retry_attempt": policy.retry_attempt,
                    "retry_budget": policy.retry_budget,
                },
            )

        next_retry_attempt = (
            policy.retry_attempt + 1
            if policy.retry_attempt < policy.retry_budget
            else None
        )
        return WalletReconciliationRetryWorkResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            retry_result_category=WALLET_RETRY_WORK_DECISION_ACCEPTED,
            accepted_for_retry=True,
            retry_attempt=policy.retry_attempt,
            retry_budget=policy.retry_budget,
            next_retry_attempt=next_retry_attempt,
            notes={
                "worker_action": policy.worker_action,
                "retry_budget_remaining": policy.retry_budget - policy.retry_attempt,
            },
        )


def _validate_retry_work_policy(policy: WalletReconciliationRetryWorkPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if (
        not isinstance(policy.correction_result_category, str)
        or policy.correction_result_category not in _WALLET_RETRY_VALID_CORRECTION_RESULT_CATEGORIES
    ):
        return "correction_result_category_invalid"
    if policy.correction_blocked_reason is not None and not isinstance(policy.correction_blocked_reason, str):
        return "correction_blocked_reason_must_be_str_or_none"
    if isinstance(policy.retry_attempt, bool) or not isinstance(policy.retry_attempt, int):
        return "retry_attempt_must_be_int"
    if policy.retry_attempt < 1:
        return "retry_attempt_must_be_positive"
    if isinstance(policy.retry_budget, bool) or not isinstance(policy.retry_budget, int):
        return "retry_budget_must_be_int"
    if policy.retry_budget < 1:
        return "retry_budget_must_be_positive"
    if policy.retry_budget > WALLET_RETRY_WORK_MAX_BUDGET:
        return "retry_budget_exceeds_max"
    if not isinstance(policy.worker_action, str) or policy.worker_action not in _WALLET_RETRY_VALID_WORKER_ACTIONS:
        return "worker_action_invalid"
    return None


def _is_retryable_correction_path(policy: WalletReconciliationRetryWorkPolicy) -> bool:
    if policy.correction_result_category == WALLET_CORRECTION_RESULT_PATH_BLOCKED:
        return True
    return (
        policy.correction_result_category == WALLET_CORRECTION_RESULT_BLOCKED
        and policy.correction_blocked_reason in _WALLET_RETRY_RETRYABLE_CORRECTION_BLOCKS
    )


def _blocked_retry_work_result(
    *,
    policy: WalletReconciliationRetryWorkPolicy,
    blocked_reason: str,
    retry_result_category: str,
    notes: dict[str, Any] | None,
) -> WalletReconciliationRetryWorkResult:
    return WalletReconciliationRetryWorkResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        retry_result_category=retry_result_category,
        accepted_for_retry=False,
        retry_attempt=policy.retry_attempt,
        retry_budget=policy.retry_budget,
        next_retry_attempt=None,
        notes=notes,
    )


@dataclass(frozen=True)
class WalletPublicReadinessPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    state_read_batch_ready: bool
    reconciliation_outcome: str
    correction_result_category: str
    retry_result_category: str


@dataclass(frozen=True)
class WalletPublicReadinessResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    readiness_result_category: str
    readiness_notes: list[str]
    notes: dict[str, Any] | None = None


_WALLET_PUBLIC_READINESS_VALID_RECONCILIATION_OUTCOMES: frozenset[str] = frozenset({
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_STATE_MISSING,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RECONCILIATION_OUTCOME_SNAPSHOT_MISMATCH,
})
_WALLET_PUBLIC_READINESS_VALID_CORRECTION_RESULTS: frozenset[str] = frozenset({
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_CORRECTION_RESULT_PATH_BLOCKED,
    WALLET_CORRECTION_RESULT_NOT_REQUIRED,
})
_WALLET_PUBLIC_READINESS_VALID_RETRY_RESULTS: frozenset[str] = frozenset({
    WALLET_RETRY_WORK_DECISION_ACCEPTED,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
    WALLET_RETRY_WORK_DECISION_BLOCKED,
    WALLET_RETRY_WORK_DECISION_EXHAUSTED,
})


class WalletPublicReadinessBoundary:
    """Phase 6.6.5 narrow public-readiness slice opener.
    Evaluate deterministic go-live preparation status from existing 6.5.x/6.6.x inputs only.
    Evaluation-only contract: no activation, scheduler, or orchestration rollout."""

    def evaluate_public_readiness(self, policy: WalletPublicReadinessPolicy) -> WalletPublicReadinessResult:
        contract_error = _validate_public_readiness_policy(policy)
        if contract_error is not None:
            return _blocked_public_readiness_result(
                policy=policy,
                blocked_reason=WALLET_PUBLIC_READINESS_BLOCK_INVALID_CONTRACT,
                readiness_notes=["contract_error"],
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_public_readiness_result(
                policy=policy,
                blocked_reason=WALLET_PUBLIC_READINESS_BLOCK_OWNERSHIP_MISMATCH,
                readiness_notes=["owner_mismatch"],
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_public_readiness_result(
                policy=policy,
                blocked_reason=WALLET_PUBLIC_READINESS_BLOCK_WALLET_NOT_ACTIVE,
                readiness_notes=["wallet_not_active"],
                notes={"wallet_active": False},
            )

        if policy.state_read_batch_ready is not True:
            return _blocked_public_readiness_result(
                policy=policy,
                blocked_reason=WALLET_PUBLIC_READINESS_BLOCK_STATE_READ_NOT_READY,
                readiness_notes=["state_read_batch_not_ready"],
                notes={"state_read_batch_ready": False},
            )

        if policy.reconciliation_outcome != WALLET_RECONCILIATION_OUTCOME_MATCH:
            return _blocked_public_readiness_result(
                policy=policy,
                blocked_reason=WALLET_PUBLIC_READINESS_BLOCK_RECONCILIATION_UNRESOLVED,
                readiness_notes=["reconciliation_unresolved"],
                notes={"reconciliation_outcome": policy.reconciliation_outcome},
            )

        readiness_notes = [
            "state_boundary_ready",
            "reconciliation_match",
        ]

        if policy.correction_result_category == WALLET_CORRECTION_RESULT_NOT_REQUIRED:
            readiness_notes.append("correction_not_required")
        elif policy.correction_result_category == WALLET_CORRECTION_RESULT_ACCEPTED:
            readiness_notes.append("correction_applied")
        else:
            return WalletPublicReadinessResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
                readiness_notes=readiness_notes + ["correction_resolution_pending"],
                notes={
                    "correction_result_category": policy.correction_result_category,
                    "retry_result_category": policy.retry_result_category,
                },
            )

        if policy.retry_result_category == WALLET_RETRY_WORK_DECISION_EXHAUSTED:
            return WalletPublicReadinessResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
                readiness_notes=readiness_notes + ["retry_budget_exhausted"],
                notes={"retry_result_category": policy.retry_result_category},
            )

        if policy.retry_result_category in {
            WALLET_RETRY_WORK_DECISION_ACCEPTED,
            WALLET_RETRY_WORK_DECISION_BLOCKED,
        }:
            return WalletPublicReadinessResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_HOLD,
                readiness_notes=readiness_notes + ["retry_resolution_pending"],
                notes={"retry_result_category": policy.retry_result_category},
            )

        return WalletPublicReadinessResult(
            success=True,
            blocked_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_GO,
            readiness_notes=readiness_notes + ["retry_lane_clear"],
            notes={"retry_result_category": policy.retry_result_category},
        )


def _validate_public_readiness_policy(policy: WalletPublicReadinessPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if not isinstance(policy.state_read_batch_ready, bool):
        return "state_read_batch_ready_must_be_bool"
    if (
        not isinstance(policy.reconciliation_outcome, str)
        or policy.reconciliation_outcome not in _WALLET_PUBLIC_READINESS_VALID_RECONCILIATION_OUTCOMES
    ):
        return "reconciliation_outcome_invalid"
    if (
        not isinstance(policy.correction_result_category, str)
        or policy.correction_result_category not in _WALLET_PUBLIC_READINESS_VALID_CORRECTION_RESULTS
    ):
        return "correction_result_category_invalid"
    if (
        not isinstance(policy.retry_result_category, str)
        or policy.retry_result_category not in _WALLET_PUBLIC_READINESS_VALID_RETRY_RESULTS
    ):
        return "retry_result_category_invalid"
    return None


def _blocked_public_readiness_result(
    *,
    policy: WalletPublicReadinessPolicy,
    blocked_reason: str,
    readiness_notes: list[str],
    notes: dict[str, Any] | None,
) -> WalletPublicReadinessResult:
    return WalletPublicReadinessResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        readiness_result_category=WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
        readiness_notes=readiness_notes,
        notes=notes,
    )


WALLET_ACTIVATION_GATE_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_ACTIVATION_GATE_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_ACTIVATION_GATE_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_ACTIVATION_GATE_BLOCK_READINESS_HOLD = "readiness_hold"
WALLET_ACTIVATION_GATE_BLOCK_READINESS_BLOCKED = "readiness_blocked"
WALLET_ACTIVATION_GATE_RESULT_ALLOWED = "allowed"
WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD = "denied_hold"
WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED = "denied_blocked"

_WALLET_ACTIVATION_GATE_VALID_READINESS_RESULTS: frozenset[str] = frozenset({
    WALLET_PUBLIC_READINESS_RESULT_GO,
    WALLET_PUBLIC_READINESS_RESULT_HOLD,
    WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
})


@dataclass(frozen=True)
class WalletPublicActivationGatePolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    readiness_result_category: str
    readiness_notes: list[str]


@dataclass(frozen=True)
class WalletPublicActivationGateResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    activation_result_category: str
    activation_notes: list[str]
    notes: dict[str, Any] | None = None


class WalletPublicActivationGateBoundary:
    """Phase 6.6.6 narrow public activation gate.
    Consumes 6.6.5 readiness outcome and deterministically allows or blocks activation.
    Gate-only: no scheduler daemon, no automation rollout, no live trading claim."""

    def evaluate_activation_gate(
        self, policy: WalletPublicActivationGatePolicy
    ) -> WalletPublicActivationGateResult:
        contract_error = _validate_activation_gate_policy(policy)
        if contract_error is not None:
            return _blocked_activation_gate_result(
                policy=policy,
                blocked_reason=WALLET_ACTIVATION_GATE_BLOCK_INVALID_CONTRACT,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
                activation_notes=["contract_error"],
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_activation_gate_result(
                policy=policy,
                blocked_reason=WALLET_ACTIVATION_GATE_BLOCK_OWNERSHIP_MISMATCH,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
                activation_notes=["owner_mismatch"],
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_activation_gate_result(
                policy=policy,
                blocked_reason=WALLET_ACTIVATION_GATE_BLOCK_WALLET_NOT_ACTIVE,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
                activation_notes=["wallet_not_active"],
                notes={"wallet_active": False},
            )

        if policy.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_GO:
            return WalletPublicActivationGateResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
                activation_notes=list(policy.readiness_notes) + ["readiness_go_confirmed"],
                notes={"readiness_result_category": policy.readiness_result_category},
            )

        if policy.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_HOLD:
            return _blocked_activation_gate_result(
                policy=policy,
                blocked_reason=WALLET_ACTIVATION_GATE_BLOCK_READINESS_HOLD,
                activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
                activation_notes=list(policy.readiness_notes) + ["readiness_hold_pending"],
                notes={"readiness_result_category": policy.readiness_result_category},
            )

        return _blocked_activation_gate_result(
            policy=policy,
            blocked_reason=WALLET_ACTIVATION_GATE_BLOCK_READINESS_BLOCKED,
            activation_result_category=WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
            activation_notes=list(policy.readiness_notes) + ["readiness_blocked"],
            notes={"readiness_result_category": policy.readiness_result_category},
        )


def _validate_activation_gate_policy(policy: WalletPublicActivationGatePolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if (
        not isinstance(policy.readiness_result_category, str)
        or policy.readiness_result_category not in _WALLET_ACTIVATION_GATE_VALID_READINESS_RESULTS
    ):
        return "readiness_result_category_invalid"
    if not isinstance(policy.readiness_notes, list):
        return "readiness_notes_must_be_list"
    return None


def _blocked_activation_gate_result(
    *,
    policy: WalletPublicActivationGatePolicy,
    blocked_reason: str,
    activation_result_category: str,
    activation_notes: list[str],
    notes: dict[str, Any] | None,
) -> WalletPublicActivationGateResult:
    return WalletPublicActivationGateResult(
        success=False,
        blocked_reason=blocked_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        activation_result_category=activation_result_category,
        activation_notes=activation_notes,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Phase 6.6.7 -- Minimal Public Activation Flow
# ---------------------------------------------------------------------------

ACTIVATION_FLOW_STOP_INVALID_CONTRACT = "invalid_contract"
ACTIVATION_FLOW_STOP_GATE_DENIED_HOLD = "gate_denied_hold"
ACTIVATION_FLOW_STOP_GATE_DENIED_BLOCKED = "gate_denied_blocked"
ACTIVATION_FLOW_RESULT_COMPLETED = "completed"
ACTIVATION_FLOW_RESULT_STOPPED_HOLD = "stopped_hold"
ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED = "stopped_blocked"

_ACTIVATION_FLOW_VALID_READINESS_RESULTS: frozenset[str] = frozenset({
    WALLET_PUBLIC_READINESS_RESULT_GO,
    WALLET_PUBLIC_READINESS_RESULT_HOLD,
    WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
})
_ACTIVATION_FLOW_VALID_GATE_RESULTS: frozenset[str] = frozenset({
    WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
})


@dataclass(frozen=True)
class MinimalPublicActivationFlowPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requester_user_id: str
    wallet_active: bool
    readiness_result_category: str
    readiness_notes: list[str]
    activation_result_category: str
    activation_notes: list[str]


@dataclass(frozen=True)
class MinimalPublicActivationFlowResult:
    flow_completed: bool
    stop_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    flow_result_category: str
    flow_notes: list[str]
    notes: dict[str, Any] | None


class MinimalPublicActivationFlowBoundary:
    """Phase 6.6.7 thin orchestration slice.
    Consumes declared 6.6.5 readiness and 6.6.6 gate outputs and routes
    deterministically to completed / stopped_hold / stopped_blocked.
    No scheduler, no automation, no live trading enablement.
    """

    def run_activation_flow(
        self, policy: MinimalPublicActivationFlowPolicy
    ) -> MinimalPublicActivationFlowResult:
        contract_error = _validate_activation_flow_policy(policy)
        if contract_error is not None:
            return _stopped_activation_flow_result(
                policy=policy,
                stop_reason=ACTIVATION_FLOW_STOP_INVALID_CONTRACT,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
                flow_notes=["contract_error"],
                notes={"contract_error": contract_error},
            )
        if policy.requester_user_id != policy.owner_user_id:
            return _stopped_activation_flow_result(
                policy=policy,
                stop_reason=ACTIVATION_FLOW_STOP_INVALID_CONTRACT,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
                flow_notes=["owner_mismatch"],
                notes={"owner_user_id": policy.owner_user_id},
            )
        if not policy.wallet_active:
            return _stopped_activation_flow_result(
                policy=policy,
                stop_reason=ACTIVATION_FLOW_STOP_INVALID_CONTRACT,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
                flow_notes=["wallet_not_active"],
                notes={"wallet_active": False},
            )

        if policy.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_ALLOWED:
            return MinimalPublicActivationFlowResult(
                flow_completed=True,
                stop_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                flow_result_category=ACTIVATION_FLOW_RESULT_COMPLETED,
                flow_notes=list(policy.activation_notes) + ["activation_gate_allowed"],
                notes={
                    "readiness_result_category": policy.readiness_result_category,
                    "activation_result_category": policy.activation_result_category,
                },
            )

        if policy.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD:
            return _stopped_activation_flow_result(
                policy=policy,
                stop_reason=ACTIVATION_FLOW_STOP_GATE_DENIED_HOLD,
                flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
                flow_notes=list(policy.activation_notes) + ["activation_gate_denied_hold"],
                notes={
                    "readiness_result_category": policy.readiness_result_category,
                    "activation_result_category": policy.activation_result_category,
                },
            )

        return _stopped_activation_flow_result(
            policy=policy,
            stop_reason=ACTIVATION_FLOW_STOP_GATE_DENIED_BLOCKED,
            flow_result_category=ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
            flow_notes=list(policy.activation_notes) + ["activation_gate_denied_blocked"],
            notes={
                "readiness_result_category": policy.readiness_result_category,
                "activation_result_category": policy.activation_result_category,
            },
        )


def _validate_activation_flow_policy(
    policy: MinimalPublicActivationFlowPolicy,
) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requester_user_id, str) or not policy.requester_user_id.strip():
        return "requester_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if (
        not isinstance(policy.readiness_result_category, str)
        or policy.readiness_result_category not in _ACTIVATION_FLOW_VALID_READINESS_RESULTS
    ):
        return "readiness_result_category_invalid"
    if not isinstance(policy.readiness_notes, list):
        return "readiness_notes_must_be_list"
    if (
        not isinstance(policy.activation_result_category, str)
        or policy.activation_result_category not in _ACTIVATION_FLOW_VALID_GATE_RESULTS
    ):
        return "activation_result_category_invalid"
    if not isinstance(policy.activation_notes, list):
        return "activation_notes_must_be_list"
    return None


def _stopped_activation_flow_result(
    *,
    policy: MinimalPublicActivationFlowPolicy,
    stop_reason: str,
    flow_result_category: str,
    flow_notes: list[str],
    notes: dict[str, Any] | None,
) -> MinimalPublicActivationFlowResult:
    return MinimalPublicActivationFlowResult(
        flow_completed=False,
        stop_reason=stop_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        flow_result_category=flow_result_category,
        flow_notes=flow_notes,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Phase 6.6.8 -- Public Safety Hardening
# ---------------------------------------------------------------------------

PUBLIC_SAFETY_HARDENING_OUTCOME_PASS = "pass"
PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD = "hold"
PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED = "blocked"

PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT = "invalid_contract"
PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH = "readiness_gate_mismatch"
PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH = "gate_flow_mismatch"
PUBLIC_SAFETY_HARDENING_STOP_CROSS_BOUNDARY_INCONSISTENCY = "cross_boundary_inconsistency"

PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_HOLD = "readiness_go_gate_hold"
PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_BLOCKED = "readiness_go_gate_blocked"
PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_ALLOWED = "readiness_hold_gate_allowed"
PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_BLOCKED = "readiness_hold_gate_blocked"
PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_ALLOWED = "readiness_blocked_gate_allowed"
PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_HOLD = "readiness_blocked_gate_hold"
PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_HOLD = "gate_allowed_flow_hold"
PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_BLOCKED = "gate_allowed_flow_blocked"
PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_COMPLETED = "gate_hold_flow_completed"
PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_BLOCKED = "gate_hold_flow_blocked"
PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_COMPLETED = "gate_blocked_flow_completed"
PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_HOLD = "gate_blocked_flow_hold"

_HARDENING_VALID_READINESS_RESULTS: frozenset[str] = frozenset({
    WALLET_PUBLIC_READINESS_RESULT_GO,
    WALLET_PUBLIC_READINESS_RESULT_HOLD,
    WALLET_PUBLIC_READINESS_RESULT_BLOCKED,
})
_HARDENING_VALID_GATE_RESULTS: frozenset[str] = frozenset({
    WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
})
_HARDENING_VALID_FLOW_RESULTS: frozenset[str] = frozenset({
    ACTIVATION_FLOW_RESULT_COMPLETED,
    ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
    ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
})

# (readiness, gate) -> mismatch name.  Keys absent from this map are consistent.
_READINESS_GATE_MISMATCH_MAP: dict[tuple[str, str], str] = {
    (WALLET_PUBLIC_READINESS_RESULT_GO, WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD):
        PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_HOLD,
    (WALLET_PUBLIC_READINESS_RESULT_GO, WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_BLOCKED,
    (WALLET_PUBLIC_READINESS_RESULT_HOLD, WALLET_ACTIVATION_GATE_RESULT_ALLOWED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_ALLOWED,
    (WALLET_PUBLIC_READINESS_RESULT_HOLD, WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_BLOCKED,
    (WALLET_PUBLIC_READINESS_RESULT_BLOCKED, WALLET_ACTIVATION_GATE_RESULT_ALLOWED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_ALLOWED,
    (WALLET_PUBLIC_READINESS_RESULT_BLOCKED, WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD):
        PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_HOLD,
}

# (gate, flow) -> mismatch name.  Keys absent from this map are consistent.
_GATE_FLOW_MISMATCH_MAP: dict[tuple[str, str], str] = {
    (WALLET_ACTIVATION_GATE_RESULT_ALLOWED, ACTIVATION_FLOW_RESULT_STOPPED_HOLD):
        PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_HOLD,
    (WALLET_ACTIVATION_GATE_RESULT_ALLOWED, ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_BLOCKED,
    (WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD, ACTIVATION_FLOW_RESULT_COMPLETED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_COMPLETED,
    (WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD, ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_BLOCKED,
    (WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED, ACTIVATION_FLOW_RESULT_COMPLETED):
        PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_COMPLETED,
    (WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED, ACTIVATION_FLOW_RESULT_STOPPED_HOLD):
        PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_HOLD,
}

# Mismatch names that escalate the outcome to BLOCKED (not merely HOLD).
_HARDENING_BLOCKED_MISMATCH_NAMES: frozenset[str] = frozenset({
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_GO_GATE_BLOCKED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_HOLD_GATE_ALLOWED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_ALLOWED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_READINESS_BLOCKED_GATE_HOLD,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_HOLD,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_ALLOWED_FLOW_BLOCKED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_HOLD_FLOW_COMPLETED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_COMPLETED,
    PUBLIC_SAFETY_HARDENING_MISMATCH_GATE_BLOCKED_FLOW_HOLD,
})


@dataclass(frozen=True)
class PublicSafetyHardeningPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requester_user_id: str
    wallet_active: bool
    readiness_result_category: str
    activation_result_category: str
    flow_result_category: str


@dataclass(frozen=True)
class PublicSafetyHardeningResult:
    hardening_outcome: str
    mismatch_block_reason: str | None
    stop_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    hardening_notes: list[str]
    notes: dict[str, Any] | None = None


class PublicSafetyHardeningBoundary:
    """Phase 6.6.8 cross-boundary public safety hardening.
    Detects inconsistent cross-boundary combinations across 6.6.5/6.6.6/6.6.7 outputs.
    Hardening-only: no scheduler daemon, no live trading rollout, no portfolio orchestration."""

    def check_hardening(
        self, policy: PublicSafetyHardeningPolicy
    ) -> PublicSafetyHardeningResult:
        contract_error = _validate_hardening_policy(policy)
        if contract_error is not None:
            return PublicSafetyHardeningResult(
                hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
                mismatch_block_reason=None,
                stop_reason=PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                hardening_notes=["contract_error"],
                notes={"contract_error": contract_error},
            )

        if policy.requester_user_id != policy.owner_user_id:
            return PublicSafetyHardeningResult(
                hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
                mismatch_block_reason=None,
                stop_reason=PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                hardening_notes=["owner_mismatch"],
                notes={"owner_user_id": policy.owner_user_id},
            )

        if not policy.wallet_active:
            return PublicSafetyHardeningResult(
                hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
                mismatch_block_reason=None,
                stop_reason=PUBLIC_SAFETY_HARDENING_STOP_INVALID_CONTRACT,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                hardening_notes=["wallet_not_active"],
                notes={"wallet_active": False},
            )

        rg_pair = (policy.readiness_result_category, policy.activation_result_category)
        gf_pair = (policy.activation_result_category, policy.flow_result_category)

        rg_mismatch = _READINESS_GATE_MISMATCH_MAP.get(rg_pair)
        gf_mismatch = _GATE_FLOW_MISMATCH_MAP.get(gf_pair)

        if rg_mismatch is None and gf_mismatch is None:
            return PublicSafetyHardeningResult(
                hardening_outcome=PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
                mismatch_block_reason=None,
                stop_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                hardening_notes=["readiness_gate_consistent", "gate_flow_consistent"],
                notes={
                    "readiness_result_category": policy.readiness_result_category,
                    "activation_result_category": policy.activation_result_category,
                    "flow_result_category": policy.flow_result_category,
                },
            )

        mismatch_names: list[str] = []
        if rg_mismatch is not None:
            mismatch_names.append(rg_mismatch)
        if gf_mismatch is not None:
            mismatch_names.append(gf_mismatch)

        has_blocked_mismatch = any(m in _HARDENING_BLOCKED_MISMATCH_NAMES for m in mismatch_names)

        if rg_mismatch is not None and gf_mismatch is not None:
            stop_reason = PUBLIC_SAFETY_HARDENING_STOP_CROSS_BOUNDARY_INCONSISTENCY
        elif rg_mismatch is not None:
            stop_reason = PUBLIC_SAFETY_HARDENING_STOP_READINESS_GATE_MISMATCH
        else:
            stop_reason = PUBLIC_SAFETY_HARDENING_STOP_GATE_FLOW_MISMATCH

        outcome = (
            PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED
            if has_blocked_mismatch
            else PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD
        )

        return PublicSafetyHardeningResult(
            hardening_outcome=outcome,
            mismatch_block_reason=mismatch_names[0],
            stop_reason=stop_reason,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            hardening_notes=mismatch_names,
            notes={
                "readiness_result_category": policy.readiness_result_category,
                "activation_result_category": policy.activation_result_category,
                "flow_result_category": policy.flow_result_category,
                "mismatches": mismatch_names,
            },
        )


def _validate_hardening_policy(policy: PublicSafetyHardeningPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requester_user_id, str) or not policy.requester_user_id.strip():
        return "requester_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if (
        not isinstance(policy.readiness_result_category, str)
        or policy.readiness_result_category not in _HARDENING_VALID_READINESS_RESULTS
    ):
        return "readiness_result_category_invalid"
    if (
        not isinstance(policy.activation_result_category, str)
        or policy.activation_result_category not in _HARDENING_VALID_GATE_RESULTS
    ):
        return "activation_result_category_invalid"
    if (
        not isinstance(policy.flow_result_category, str)
        or policy.flow_result_category not in _HARDENING_VALID_FLOW_RESULTS
    ):
        return "flow_result_category_invalid"
    return None


# ---------------------------------------------------------------------------
# Phase 6.6.9 -- Minimal Execution Hook
# ---------------------------------------------------------------------------

EXECUTION_HOOK_STOP_INVALID_CONTRACT = "invalid_contract"
EXECUTION_HOOK_STOP_HARDENING_BLOCKED = "hardening_blocked"
EXECUTION_HOOK_STOP_HARDENING_HOLD = "hardening_hold"
EXECUTION_HOOK_STOP_FLOW_NOT_COMPLETED = "flow_not_completed"
EXECUTION_HOOK_STOP_GATE_NOT_ALLOWED = "gate_not_allowed"

EXECUTION_HOOK_RESULT_EXECUTED = "executed"
EXECUTION_HOOK_RESULT_STOPPED_HOLD = "stopped_hold"
EXECUTION_HOOK_RESULT_STOPPED_BLOCKED = "stopped_blocked"

_EXECUTION_HOOK_VALID_HARDENING_OUTCOMES: frozenset[str] = frozenset({
    PUBLIC_SAFETY_HARDENING_OUTCOME_PASS,
    PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD,
    PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED,
})
_EXECUTION_HOOK_VALID_FLOW_RESULTS: frozenset[str] = frozenset({
    ACTIVATION_FLOW_RESULT_COMPLETED,
    ACTIVATION_FLOW_RESULT_STOPPED_HOLD,
    ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED,
})
_EXECUTION_HOOK_VALID_GATE_RESULTS: frozenset[str] = frozenset({
    WALLET_ACTIVATION_GATE_RESULT_ALLOWED,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD,
    WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED,
})


@dataclass(frozen=True)
class MinimalExecutionHookPolicy:
    wallet_binding_id: str
    owner_user_id: str
    requester_user_id: str
    wallet_active: bool
    hardening_outcome: str
    flow_result_category: str
    activation_result_category: str


@dataclass(frozen=True)
class MinimalExecutionHookResult:
    hook_executed: bool
    stop_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    hook_result_category: str
    execution_hook_notes: list[str]
    notes: dict[str, Any] | None = None


class MinimalExecutionHookBoundary:
    """Phase 6.6.9 minimal execution hook.
    Executes only when the cross-boundary path is explicitly safe and completed.
    Consumes declared outputs from 6.6.6 gate, 6.6.7 flow, and 6.6.8 hardening.
    Hook-only: no scheduler daemon, no live trading rollout, no portfolio orchestration."""

    def execute_hook(
        self, policy: MinimalExecutionHookPolicy
    ) -> MinimalExecutionHookResult:
        contract_error = _validate_execution_hook_policy(policy)
        if contract_error is not None:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_INVALID_CONTRACT,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_BLOCKED,
                execution_hook_notes=["contract_error"],
                notes={"contract_error": contract_error},
            )

        if policy.requester_user_id != policy.owner_user_id:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_INVALID_CONTRACT,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_BLOCKED,
                execution_hook_notes=["owner_mismatch"],
                notes={"owner_user_id": policy.owner_user_id},
            )

        if not policy.wallet_active:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_INVALID_CONTRACT,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_BLOCKED,
                execution_hook_notes=["wallet_not_active"],
                notes={"wallet_active": False},
            )

        if policy.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_HARDENING_BLOCKED,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_BLOCKED,
                execution_hook_notes=["hardening_blocked"],
                notes={"hardening_outcome": policy.hardening_outcome},
            )

        if policy.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_HARDENING_HOLD,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_HOLD,
                execution_hook_notes=["hardening_hold"],
                notes={"hardening_outcome": policy.hardening_outcome},
            )

        # hardening_outcome == PASS from here
        if policy.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_FLOW_NOT_COMPLETED,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_BLOCKED,
                execution_hook_notes=["flow_stopped_blocked"],
                notes={
                    "hardening_outcome": policy.hardening_outcome,
                    "flow_result_category": policy.flow_result_category,
                },
            )

        if policy.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_HOLD:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_FLOW_NOT_COMPLETED,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_HOLD,
                execution_hook_notes=["flow_stopped_hold"],
                notes={
                    "hardening_outcome": policy.hardening_outcome,
                    "flow_result_category": policy.flow_result_category,
                },
            )

        # flow_result_category == COMPLETED from here
        if policy.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_GATE_NOT_ALLOWED,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_BLOCKED,
                execution_hook_notes=["gate_denied_blocked"],
                notes={
                    "hardening_outcome": policy.hardening_outcome,
                    "flow_result_category": policy.flow_result_category,
                    "activation_result_category": policy.activation_result_category,
                },
            )

        if policy.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD:
            return _stopped_execution_hook_result(
                policy=policy,
                stop_reason=EXECUTION_HOOK_STOP_GATE_NOT_ALLOWED,
                hook_result_category=EXECUTION_HOOK_RESULT_STOPPED_HOLD,
                execution_hook_notes=["gate_denied_hold"],
                notes={
                    "hardening_outcome": policy.hardening_outcome,
                    "flow_result_category": policy.flow_result_category,
                    "activation_result_category": policy.activation_result_category,
                },
            )

        return MinimalExecutionHookResult(
            hook_executed=True,
            stop_reason=None,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            hook_result_category=EXECUTION_HOOK_RESULT_EXECUTED,
            execution_hook_notes=["hardening_pass", "flow_completed", "gate_allowed"],
            notes={
                "hardening_outcome": policy.hardening_outcome,
                "flow_result_category": policy.flow_result_category,
                "activation_result_category": policy.activation_result_category,
            },
        )


def _validate_execution_hook_policy(policy: MinimalExecutionHookPolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requester_user_id, str) or not policy.requester_user_id.strip():
        return "requester_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if (
        not isinstance(policy.hardening_outcome, str)
        or policy.hardening_outcome not in _EXECUTION_HOOK_VALID_HARDENING_OUTCOMES
    ):
        return "hardening_outcome_invalid"
    if (
        not isinstance(policy.flow_result_category, str)
        or policy.flow_result_category not in _EXECUTION_HOOK_VALID_FLOW_RESULTS
    ):
        return "flow_result_category_invalid"
    if (
        not isinstance(policy.activation_result_category, str)
        or policy.activation_result_category not in _EXECUTION_HOOK_VALID_GATE_RESULTS
    ):
        return "activation_result_category_invalid"
    return None


def _stopped_execution_hook_result(
    *,
    policy: MinimalExecutionHookPolicy,
    stop_reason: str,
    hook_result_category: str,
    execution_hook_notes: list[str],
    notes: dict[str, Any] | None,
) -> MinimalExecutionHookResult:
    return MinimalExecutionHookResult(
        hook_executed=False,
        stop_reason=stop_reason,
        wallet_binding_id=policy.wallet_binding_id,
        owner_user_id=policy.owner_user_id,
        hook_result_category=hook_result_category,
        execution_hook_notes=execution_hook_notes,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Phase 7.0 -- Public Activation Cycle Orchestration Foundation
# ---------------------------------------------------------------------------

PUBLIC_ACTIVATION_CYCLE_RESULT_COMPLETED = "completed"
PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD = "stopped_hold"
PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED = "stopped_blocked"

PUBLIC_ACTIVATION_CYCLE_STOP_INVALID_CONTRACT = "invalid_contract"
PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_HOLD = "readiness_hold"
PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_BLOCKED = "readiness_blocked"
PUBLIC_ACTIVATION_CYCLE_STOP_GATE_DENIED_HOLD = "gate_denied_hold"
PUBLIC_ACTIVATION_CYCLE_STOP_GATE_DENIED_BLOCKED = "gate_denied_blocked"
PUBLIC_ACTIVATION_CYCLE_STOP_FLOW_STOPPED_HOLD = "flow_stopped_hold"
PUBLIC_ACTIVATION_CYCLE_STOP_FLOW_STOPPED_BLOCKED = "flow_stopped_blocked"
PUBLIC_ACTIVATION_CYCLE_STOP_HARDENING_HOLD = "hardening_hold"
PUBLIC_ACTIVATION_CYCLE_STOP_HARDENING_BLOCKED = "hardening_blocked"
PUBLIC_ACTIVATION_CYCLE_STOP_HOOK_STOPPED_HOLD = "hook_stopped_hold"
PUBLIC_ACTIVATION_CYCLE_STOP_HOOK_STOPPED_BLOCKED = "hook_stopped_blocked"


@dataclass(frozen=True)
class PublicActivationCyclePolicy:
    wallet_binding_id: str
    owner_user_id: str
    requester_user_id: str
    wallet_active: bool
    state_read_batch_ready: bool
    reconciliation_outcome: str
    correction_result_category: str
    retry_result_category: str


@dataclass(frozen=True)
class PublicActivationCycleResult:
    cycle_completed: bool
    cycle_result_category: str
    cycle_stop_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    cycle_notes: list[str]
    readiness_result: WalletPublicReadinessResult
    activation_gate_result: WalletPublicActivationGateResult
    activation_flow_result: MinimalPublicActivationFlowResult
    hardening_result: PublicSafetyHardeningResult
    execution_hook_result: MinimalExecutionHookResult
    notes: dict[str, Any] | None = None


class PublicActivationCycleOrchestrationBoundary:
    """Phase 7.0 thin deterministic public activation cycle orchestration.
    Runs one synchronous pass through readiness -> gate -> flow -> hardening -> execution hook.
    No scheduler daemon, no async worker mesh, and no live-trading rollout."""

    def run_public_activation_cycle(
        self, policy: PublicActivationCyclePolicy
    ) -> PublicActivationCycleResult:
        readiness_result = WalletPublicReadinessBoundary().evaluate_public_readiness(
            WalletPublicReadinessPolicy(
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                requested_by_user_id=policy.requester_user_id,
                wallet_active=policy.wallet_active,
                state_read_batch_ready=policy.state_read_batch_ready,
                reconciliation_outcome=policy.reconciliation_outcome,
                correction_result_category=policy.correction_result_category,
                retry_result_category=policy.retry_result_category,
            )
        )

        activation_gate_result = WalletPublicActivationGateBoundary().evaluate_activation_gate(
            WalletPublicActivationGatePolicy(
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                requested_by_user_id=policy.requester_user_id,
                wallet_active=policy.wallet_active,
                readiness_result_category=readiness_result.readiness_result_category,
                readiness_notes=readiness_result.readiness_notes,
            )
        )

        activation_flow_result = MinimalPublicActivationFlowBoundary().run_activation_flow(
            MinimalPublicActivationFlowPolicy(
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                requester_user_id=policy.requester_user_id,
                wallet_active=policy.wallet_active,
                readiness_result_category=readiness_result.readiness_result_category,
                readiness_notes=readiness_result.readiness_notes,
                activation_result_category=activation_gate_result.activation_result_category,
                activation_notes=activation_gate_result.activation_notes,
            )
        )

        hardening_result = PublicSafetyHardeningBoundary().check_hardening(
            PublicSafetyHardeningPolicy(
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                requester_user_id=policy.requester_user_id,
                wallet_active=policy.wallet_active,
                readiness_result_category=readiness_result.readiness_result_category,
                activation_result_category=activation_gate_result.activation_result_category,
                flow_result_category=activation_flow_result.flow_result_category,
            )
        )

        execution_hook_result = MinimalExecutionHookBoundary().execute_hook(
            MinimalExecutionHookPolicy(
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                requester_user_id=policy.requester_user_id,
                wallet_active=policy.wallet_active,
                hardening_outcome=hardening_result.hardening_outcome,
                flow_result_category=activation_flow_result.flow_result_category,
                activation_result_category=activation_gate_result.activation_result_category,
            )
        )

        cycle_result_category, cycle_stop_reason = _determine_public_activation_cycle_outcome(
            readiness_result=readiness_result,
            activation_gate_result=activation_gate_result,
            activation_flow_result=activation_flow_result,
            hardening_result=hardening_result,
            execution_hook_result=execution_hook_result,
        )
        cycle_completed = cycle_result_category == PUBLIC_ACTIVATION_CYCLE_RESULT_COMPLETED
        cycle_notes = _compose_public_activation_cycle_notes(
            readiness_result=readiness_result,
            activation_gate_result=activation_gate_result,
            activation_flow_result=activation_flow_result,
            hardening_result=hardening_result,
            execution_hook_result=execution_hook_result,
            cycle_stop_reason=cycle_stop_reason,
        )

        return PublicActivationCycleResult(
            cycle_completed=cycle_completed,
            cycle_result_category=cycle_result_category,
            cycle_stop_reason=cycle_stop_reason,
            wallet_binding_id=policy.wallet_binding_id,
            owner_user_id=policy.owner_user_id,
            cycle_notes=cycle_notes,
            readiness_result=readiness_result,
            activation_gate_result=activation_gate_result,
            activation_flow_result=activation_flow_result,
            hardening_result=hardening_result,
            execution_hook_result=execution_hook_result,
            notes={
                "readiness_result_category": readiness_result.readiness_result_category,
                "activation_result_category": activation_gate_result.activation_result_category,
                "flow_result_category": activation_flow_result.flow_result_category,
                "hardening_outcome": hardening_result.hardening_outcome,
                "hook_result_category": execution_hook_result.hook_result_category,
            },
        )


def run_public_activation_cycle(policy: PublicActivationCyclePolicy) -> PublicActivationCycleResult:
    """Deterministic public activation cycle entrypoint for one synchronous run."""
    return PublicActivationCycleOrchestrationBoundary().run_public_activation_cycle(policy)


def _determine_public_activation_cycle_outcome(
    *,
    readiness_result: WalletPublicReadinessResult,
    activation_gate_result: WalletPublicActivationGateResult,
    activation_flow_result: MinimalPublicActivationFlowResult,
    hardening_result: PublicSafetyHardeningResult,
    execution_hook_result: MinimalExecutionHookResult,
) -> tuple[str, str | None]:
    if readiness_result.blocked_reason == WALLET_PUBLIC_READINESS_BLOCK_INVALID_CONTRACT:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
            PUBLIC_ACTIVATION_CYCLE_STOP_INVALID_CONTRACT,
        )
    if readiness_result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_BLOCKED:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
            PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_BLOCKED,
        )
    if readiness_result.readiness_result_category == WALLET_PUBLIC_READINESS_RESULT_HOLD:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD,
            PUBLIC_ACTIVATION_CYCLE_STOP_READINESS_HOLD,
        )
    if activation_gate_result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_BLOCKED:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
            PUBLIC_ACTIVATION_CYCLE_STOP_GATE_DENIED_BLOCKED,
        )
    if activation_gate_result.activation_result_category == WALLET_ACTIVATION_GATE_RESULT_DENIED_HOLD:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD,
            PUBLIC_ACTIVATION_CYCLE_STOP_GATE_DENIED_HOLD,
        )
    if activation_flow_result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_BLOCKED:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
            PUBLIC_ACTIVATION_CYCLE_STOP_FLOW_STOPPED_BLOCKED,
        )
    if activation_flow_result.flow_result_category == ACTIVATION_FLOW_RESULT_STOPPED_HOLD:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD,
            PUBLIC_ACTIVATION_CYCLE_STOP_FLOW_STOPPED_HOLD,
        )
    if hardening_result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_BLOCKED:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
            PUBLIC_ACTIVATION_CYCLE_STOP_HARDENING_BLOCKED,
        )
    if hardening_result.hardening_outcome == PUBLIC_SAFETY_HARDENING_OUTCOME_HOLD:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD,
            PUBLIC_ACTIVATION_CYCLE_STOP_HARDENING_HOLD,
        )
    if execution_hook_result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_BLOCKED:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
            PUBLIC_ACTIVATION_CYCLE_STOP_HOOK_STOPPED_BLOCKED,
        )
    if execution_hook_result.hook_result_category == EXECUTION_HOOK_RESULT_STOPPED_HOLD:
        return (
            PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD,
            PUBLIC_ACTIVATION_CYCLE_STOP_HOOK_STOPPED_HOLD,
        )
    return (PUBLIC_ACTIVATION_CYCLE_RESULT_COMPLETED, None)


def _compose_public_activation_cycle_notes(
    *,
    readiness_result: WalletPublicReadinessResult,
    activation_gate_result: WalletPublicActivationGateResult,
    activation_flow_result: MinimalPublicActivationFlowResult,
    hardening_result: PublicSafetyHardeningResult,
    execution_hook_result: MinimalExecutionHookResult,
    cycle_stop_reason: str | None,
) -> list[str]:
    notes: list[str] = [
        f"readiness:{readiness_result.readiness_result_category}",
        f"activation_gate:{activation_gate_result.activation_result_category}",
        f"activation_flow:{activation_flow_result.flow_result_category}",
        f"hardening:{hardening_result.hardening_outcome}",
        f"execution_hook:{execution_hook_result.hook_result_category}",
    ]
    if cycle_stop_reason is None:
        notes.append("cycle_completed")
    else:
        notes.append(f"cycle_stop_reason:{cycle_stop_reason}")
    return notes
