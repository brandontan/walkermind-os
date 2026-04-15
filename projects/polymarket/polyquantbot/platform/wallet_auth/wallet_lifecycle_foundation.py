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
