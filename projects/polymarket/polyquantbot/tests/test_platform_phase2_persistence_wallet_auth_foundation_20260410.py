from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from projects.polymarket.polyquantbot.platform.accounts.service import AccountService
from projects.polymarket.polyquantbot.platform.context.resolver import ContextResolver, LegacySessionSeed
from projects.polymarket.polyquantbot.platform.permissions.service import PermissionService
from projects.polymarket.polyquantbot.platform.storage.factory import build_repository_bundle_from_env
from projects.polymarket.polyquantbot.platform.strategy_subscriptions.service import StrategySubscriptionService
from projects.polymarket.polyquantbot.platform.wallet_auth.service import WalletAuthService


def _seed() -> LegacySessionSeed:
    return LegacySessionSeed(
        user_id="legacy-user-2",
        external_user_id="session-2",
        mode="PAPER",
        wallet_binding_id="wb-2",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="abc123",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-A",),
        trace_id="trace-2",
    )


@dataclass
class _SpyAccountRepository:
    write_calls: list[str] = field(default_factory=list)

    def get_by_user_id(self, *, user_id: str):
        return None

    def upsert(self, record):
        self.write_calls.append("upsert")
        return record


@dataclass
class _SpyWalletRepository:
    write_calls: list[str] = field(default_factory=list)

    def get_by_id(self, *, wallet_binding_id: str):
        return None

    def upsert(self, record):
        self.write_calls.append("upsert")
        return record


@dataclass
class _SpyPermissionRepository:
    write_calls: list[str] = field(default_factory=list)

    def get_by_user_id(self, *, user_id: str):
        return None

    def upsert(self, record):
        self.write_calls.append("upsert")
        return record


@dataclass
class _SpyStrategyRepository:
    write_calls: list[str] = field(default_factory=list)

    def list_by_user_id(self, *, user_id: str):
        return ()

    def upsert(self, record):
        self.write_calls.append("upsert")
        return record


def test_phase2_repository_crud_and_service_wiring() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        storage_file = Path(temp_dir) / "platform_storage.json"
        os.environ["PLATFORM_STORAGE_BACKEND"] = "json"
        os.environ["PLATFORM_STORAGE_PATH"] = str(storage_file)
        os.environ["PLATFORM_AUTH_PROVIDER"] = "polymarket"
        try:
            bundle = build_repository_bundle_from_env()
            assert bundle.accounts is not None
            assert bundle.wallet_bindings is not None
            assert bundle.permissions is not None
            assert bundle.strategy_subscriptions is not None

            account_service = AccountService(repository=bundle.accounts)
            wallet_service = WalletAuthService(repository=bundle.wallet_bindings)
            permission_service = PermissionService(repository=bundle.permissions)
            subscription_service = StrategySubscriptionService(repository=bundle.strategy_subscriptions)

            account = account_service.ensure_user_account(legacy_user_id="legacy-user-2", source_type="legacy-session")
            wallet = wallet_service.ensure_wallet_binding(
                user_id=account.user_id,
                wallet_binding_id="wb-2",
                wallet_type="LEGACY_SESSION",
                signature_type="SESSION",
                funder_address="ABC123",
                auth_state="UNVERIFIED",
                mode="PAPER",
            )
            permission = permission_service.ensure_permission_profile(
                user_id=account.user_id,
                allowed_markets=("MKT-A",),
                mode="PAPER",
            )
            subscription = subscription_service.set_subscription(
                user_id=account.user_id,
                strategy_id="S1",
                enabled=True,
                risk_budget=0.25,
            )
            assert account.user_id == "legacy-user-2"
            assert wallet.auth_provider == "polymarket"
            assert wallet.funder_address.startswith("0x")
            assert permission.version == "phase2-foundation"
            assert subscription.strategy_id == "S1"
        finally:
            os.environ.pop("PLATFORM_STORAGE_BACKEND", None)
            os.environ.pop("PLATFORM_STORAGE_PATH", None)
            os.environ.pop("PLATFORM_AUTH_PROVIDER", None)


def test_phase2_context_resolver_is_pure_no_writes() -> None:
    account_repo = _SpyAccountRepository()
    wallet_repo = _SpyWalletRepository()
    permission_repo = _SpyPermissionRepository()
    strategy_repo = _SpyStrategyRepository()

    resolver = ContextResolver(
        account_service=AccountService(repository=account_repo),
        wallet_auth_service=WalletAuthService(repository=wallet_repo),
        permission_service=PermissionService(repository=permission_repo),
        strategy_subscription_service=StrategySubscriptionService(repository=strategy_repo),
    )
    envelope = resolver.resolve(_seed())

    assert envelope.execution_context.trace_id == "trace-2"
    assert account_repo.write_calls == []
    assert wallet_repo.write_calls == []
    assert permission_repo.write_calls == []
    assert strategy_repo.write_calls == []


def test_service_split_resolve_vs_ensure_write_behavior() -> None:
    account_repo = _SpyAccountRepository()
    wallet_repo = _SpyWalletRepository()
    permission_repo = _SpyPermissionRepository()

    account_service = AccountService(repository=account_repo)
    wallet_service = WalletAuthService(repository=wallet_repo)
    permission_service = PermissionService(repository=permission_repo)

    account_service.resolve_user_account(legacy_user_id="legacy-user-9")
    wallet_service.resolve_wallet_binding(
        user_id="legacy-user-9",
        wallet_binding_id="wb-9",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="abc123",
        auth_state="UNVERIFIED",
        mode="PAPER",
    )
    permission_service.resolve_permission_profile(
        user_id="legacy-user-9",
        allowed_markets=("MKT-9",),
        mode="PAPER",
    )
    assert account_repo.write_calls == []
    assert wallet_repo.write_calls == []
    assert permission_repo.write_calls == []

    account_service.ensure_user_account(legacy_user_id="legacy-user-9")
    wallet_service.ensure_wallet_binding(
        user_id="legacy-user-9",
        wallet_binding_id="wb-9",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="abc123",
        auth_state="UNVERIFIED",
        mode="PAPER",
    )
    permission_service.ensure_permission_profile(
        user_id="legacy-user-9",
        allowed_markets=("MKT-9",),
        mode="PAPER",
    )
    assert account_repo.write_calls == ["upsert"]
    assert wallet_repo.write_calls == ["upsert"]
    assert permission_repo.write_calls == ["upsert"]
