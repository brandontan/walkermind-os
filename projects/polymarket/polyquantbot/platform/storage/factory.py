from __future__ import annotations

import os
from dataclasses import dataclass

from .local_json_backend import LocalJsonBackend
from .local_json_repositories import (
    LocalJsonAuditEventRepository,
    LocalJsonExecutionContextRepository,
    LocalJsonPermissionProfileRepository,
    LocalJsonStrategySubscriptionRepository,
    LocalJsonUserAccountRepository,
    LocalJsonWalletBindingRepository,
)
from .repositories import (
    AuditEventRepository,
    ExecutionContextRepository,
    PermissionProfileRepository,
    StrategySubscriptionRepository,
    UserAccountRepository,
    WalletBindingRepository,
)


@dataclass(frozen=True)
class RepositoryBundle:
    accounts: UserAccountRepository | None
    wallet_bindings: WalletBindingRepository | None
    permissions: PermissionProfileRepository | None
    strategy_subscriptions: StrategySubscriptionRepository | None
    execution_contexts: ExecutionContextRepository | None
    audit_events: AuditEventRepository | None


def build_repository_bundle_from_env() -> RepositoryBundle:
    backend_name = os.getenv("PLATFORM_STORAGE_BACKEND", "none").strip().lower()
    storage_path = os.getenv(
        "PLATFORM_STORAGE_PATH",
        "/tmp/polyquantbot_platform_storage_phase2.json",
    ).strip()
    if backend_name not in {"json", "sqlite"}:
        return RepositoryBundle(None, None, None, None, None, None)

    backend = LocalJsonBackend(storage_path=storage_path)
    return RepositoryBundle(
        accounts=LocalJsonUserAccountRepository(backend),
        wallet_bindings=LocalJsonWalletBindingRepository(backend),
        permissions=LocalJsonPermissionProfileRepository(backend),
        strategy_subscriptions=LocalJsonStrategySubscriptionRepository(backend),
        execution_contexts=LocalJsonExecutionContextRepository(backend),
        audit_events=LocalJsonAuditEventRepository(backend),
    )
