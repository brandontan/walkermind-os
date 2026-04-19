"""Client auth handoff contract — minimal trusted client identity handoff validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SUPPORTED_CLIENT_TYPES: frozenset[str] = frozenset({"telegram", "web"})

HandoffOutcome = Literal[
    "valid",
    "rejected_empty_claim",
    "rejected_empty_scope",
    "rejected_unsupported_client_type",
]


@dataclass(frozen=True)
class ClientHandoffContract:
    client_type: str
    client_identity_claim: str
    tenant_id: str
    user_id: str
    ttl_seconds: int = 1800


@dataclass(frozen=True)
class ClientHandoffValidation:
    outcome: HandoffOutcome
    detail: str = ""
    auth_method: str = ""


def validate_client_handoff(contract: ClientHandoffContract) -> ClientHandoffValidation:
    """Validates the client handoff contract before session issuance.

    Validates structural contract only: known client_type, non-empty claim, non-empty scope.
    Cryptographic or UX-level identity verification is a future production gate, out of scope here.
    """
    if not contract.client_type.strip() or contract.client_type not in SUPPORTED_CLIENT_TYPES:
        return ClientHandoffValidation(
            outcome="rejected_unsupported_client_type",
            detail=f"unsupported client_type: {contract.client_type!r}",
        )
    if not contract.client_identity_claim.strip():
        return ClientHandoffValidation(
            outcome="rejected_empty_claim",
            detail="client_identity_claim must not be empty",
        )
    if not contract.tenant_id.strip() or not contract.user_id.strip():
        return ClientHandoffValidation(
            outcome="rejected_empty_scope",
            detail="tenant_id and user_id must not be empty",
        )
    return ClientHandoffValidation(
        outcome="valid",
        auth_method=contract.client_type,
    )
