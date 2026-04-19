"""Tenant/user scope resolution and ownership guards for multi-user foundation."""
from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.server.schemas.multi_user import OwnershipCheckResult, ScopeContext


class ScopeResolutionError(RuntimeError):
    """Raised when tenant/user scope cannot be resolved safely."""


@dataclass(frozen=True)
class ResourceOwnership:
    resource_type: str
    resource_id: str
    tenant_id: str
    user_id: str


def resolve_scope(tenant_id: str | None, user_id: str | None) -> ScopeContext:
    if not tenant_id or not tenant_id.strip():
        raise ScopeResolutionError("tenant_id is required for scope resolution")
    if not user_id or not user_id.strip():
        raise ScopeResolutionError("user_id is required for scope resolution")
    return ScopeContext(tenant_id=tenant_id.strip(), user_id=user_id.strip())


def check_ownership(scope: ScopeContext, ownership: ResourceOwnership) -> OwnershipCheckResult:
    is_owner = scope.user_id == ownership.user_id and scope.tenant_id == ownership.tenant_id
    return OwnershipCheckResult(
        resource_type=ownership.resource_type,
        resource_id=ownership.resource_id,
        owner_user_id=ownership.user_id,
        owner_tenant_id=ownership.tenant_id,
        is_owner=is_owner,
    )


def require_ownership(scope: ScopeContext, ownership: ResourceOwnership) -> None:
    check = check_ownership(scope=scope, ownership=ownership)
    if not check.is_owner:
        raise ScopeResolutionError(
            f"scope mismatch for {check.resource_type}:{check.resource_id} "
            f"expected tenant={check.owner_tenant_id} user={check.owner_user_id}"
        )
