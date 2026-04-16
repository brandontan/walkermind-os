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
