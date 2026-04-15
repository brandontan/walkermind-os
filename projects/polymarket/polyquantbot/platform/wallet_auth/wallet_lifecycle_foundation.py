from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

WALLET_SECRET_LOAD_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_SECRET_LOAD_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_SECRET_LOAD_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_SECRET_LOAD_BLOCK_SECRET_MISSING = "secret_missing"
WALLET_SECRET_LOAD_BLOCK_RUNTIME_ERROR = "runtime_error"
WALLET_STATE_STORAGE_BLOCK_INVALID_CONTRACT = "invalid_contract"
WALLET_STATE_STORAGE_BLOCK_OWNERSHIP_MISMATCH = "ownership_mismatch"
WALLET_STATE_STORAGE_BLOCK_WALLET_NOT_ACTIVE = "wallet_not_active"
WALLET_STATE_STORAGE_BLOCK_INVALID_STATE = "invalid_state"
WALLET_STATE_STORAGE_BLOCK_RUNTIME_ERROR = "runtime_error"


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


@dataclass(frozen=True)
class WalletStateStoragePolicy:
    wallet_binding_id: str
    owner_user_id: str
    requested_by_user_id: str
    wallet_active: bool
    state_storage_key: str
    state_payload: dict[str, Any]


@dataclass(frozen=True)
class WalletStateStorageResult:
    success: bool
    blocked_reason: str | None
    wallet_binding_id: str
    owner_user_id: str
    state_stored: bool
    state_storage_key: str
    stored_revision: int | None
    notes: dict[str, Any] | None = None


class WalletStateStorageBoundary:
    """Phase 6.5 narrow wallet lifecycle boundary: wallet state/storage contract only."""

    def __init__(self) -> None:
        self._state_storage: dict[str, dict[str, Any]] = {}

    def store_state(self, policy: WalletStateStoragePolicy) -> WalletStateStorageResult:
        contract_error = _validate_state_storage_policy(policy)
        if contract_error is not None:
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_INVALID_CONTRACT,
                notes={"contract_error": contract_error},
            )

        if policy.requested_by_user_id != policy.owner_user_id:
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_OWNERSHIP_MISMATCH,
                notes={"owner_user_id": policy.owner_user_id},
            )

        if policy.wallet_active is not True:
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_WALLET_NOT_ACTIVE,
                notes={"wallet_active": False},
            )

        state_error = _validate_wallet_state_payload(policy.state_payload)
        if state_error is not None:
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_INVALID_STATE,
                notes={"state_error": state_error},
            )

        try:
            existing_entry = self._state_storage.get(policy.state_storage_key)
            next_revision = 1
            if existing_entry is not None:
                next_revision = int(existing_entry["revision"]) + 1

            stored_entry = {
                "wallet_binding_id": policy.wallet_binding_id,
                "owner_user_id": policy.owner_user_id,
                "state_payload": dict(policy.state_payload),
                "revision": next_revision,
            }
            self._state_storage[policy.state_storage_key] = stored_entry
            return WalletStateStorageResult(
                success=True,
                blocked_reason=None,
                wallet_binding_id=policy.wallet_binding_id,
                owner_user_id=policy.owner_user_id,
                state_stored=True,
                state_storage_key=policy.state_storage_key,
                stored_revision=next_revision,
                notes={"state_fields": sorted(policy.state_payload.keys())},
            )
        except Exception as exc:  # explicit, deterministic block with no silent failure
            return _blocked_state_storage_result(
                policy=policy,
                blocked_reason=WALLET_STATE_STORAGE_BLOCK_RUNTIME_ERROR,
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


def _validate_state_storage_policy(policy: WalletStateStoragePolicy) -> str | None:
    if not isinstance(policy.wallet_binding_id, str) or not policy.wallet_binding_id.strip():
        return "wallet_binding_id_required"
    if not isinstance(policy.owner_user_id, str) or not policy.owner_user_id.strip():
        return "owner_user_id_required"
    if not isinstance(policy.requested_by_user_id, str) or not policy.requested_by_user_id.strip():
        return "requested_by_user_id_required"
    if not isinstance(policy.wallet_active, bool):
        return "wallet_active_must_be_bool"
    if not isinstance(policy.state_storage_key, str) or not policy.state_storage_key.strip():
        return "state_storage_key_required"
    if not isinstance(policy.state_payload, dict):
        return "state_payload_must_be_dict"
    return None


def _validate_wallet_state_payload(state_payload: dict[str, Any]) -> str | None:
    required_fields = ("state_id", "status", "updated_at")
    for field_name in required_fields:
        field_value = state_payload.get(field_name)
        if not isinstance(field_value, str) or not field_value.strip():
            return f"{field_name}_required"

    status = state_payload["status"]
    allowed_status_values = {"active", "paused", "suspended"}
    if status not in allowed_status_values:
        return "status_invalid"
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
        state_storage_key=policy.state_storage_key,
        stored_revision=None,
        notes=notes,
    )


def _secret_fingerprint(secret_value: str) -> str:
    return hashlib.sha256(secret_value.encode("utf-8")).hexdigest()[:16]
