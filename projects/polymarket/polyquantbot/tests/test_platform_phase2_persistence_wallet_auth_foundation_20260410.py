from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from projects.polymarket.polyquantbot.platform.accounts.service import AccountService
from projects.polymarket.polyquantbot.platform.context.resolver import ContextResolver, LegacySessionSeed
from projects.polymarket.polyquantbot.platform.permissions.service import PermissionService
from projects.polymarket.polyquantbot.platform.storage.models import (
    PermissionProfileRecord,
    UserAccountRecord,
    WalletBindingRecord,
)
from projects.polymarket.polyquantbot.platform.storage.factory import build_repository_bundle_from_env
from projects.polymarket.polyquantbot.platform.strategy_subscriptions.service import StrategySubscriptionService
from projects.polymarket.polyquantbot.platform.wallet_auth.service import WalletAuthService


class _WriteSpy:
    def __init__(self) -> None:
        self.write_calls: list[str] = []

    def record(self, method_name: str) -> None:
        self.write_calls.append(method_name)


class _ReadOnlyAccountRepo:
    def __init__(self, spy: _WriteSpy, record: UserAccountRecord | None = None) -> None:
        self._spy = spy
        self._record = record

    def get_by_user_id(self, *, user_id: str) -> UserAccountRecord | None:
        return self._record

    def upsert(self, record: UserAccountRecord) -> UserAccountRecord:
        self._spy.record("accounts.upsert")
        return record


class _ReadOnlyWalletRepo:
    def __init__(self, spy: _WriteSpy, record: WalletBindingRecord | None = None) -> None:
        self._spy = spy
        self._record = record

    def get_by_id(self, *, wallet_binding_id: str) -> WalletBindingRecord | None:
        return self._record

    def upsert(self, record: WalletBindingRecord) -> WalletBindingRecord:
        self._spy.record("wallet_bindings.upsert")
        return record


class _ReadOnlyPermissionRepo:
    def __init__(self, spy: _WriteSpy, record: PermissionProfileRecord | None = None) -> None:
        self._spy = spy
        self._record = record

    def get_by_user_id(self, *, user_id: str) -> PermissionProfileRecord | None:
        return self._record

    def upsert(self, record: PermissionProfileRecord) -> PermissionProfileRecord:
        self._spy.record("permissions.upsert")
        return record


class _ReadOnlySubscriptionRepo:
    def __init__(self, spy: _WriteSpy) -> None:
        self._spy = spy

    def list_by_user_id(self, *, user_id: str) -> tuple:
        return ()

    def upsert(self, record) -> object:
        self._spy.record("subscriptions.upsert")
        return record


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


def test_phase2_repository_write_paths_are_explicit() -> None:
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


def test_phase2_resolver_has_no_repository_attrs_and_no_write_through_side_effects() -> None:
    fixed_ts = datetime(2026, 4, 10, 0, 0, tzinfo=timezone.utc)
    spy = _WriteSpy()
    resolver = ContextResolver(
        account_service=AccountService(
            repository=_ReadOnlyAccountRepo(
                spy,
                UserAccountRecord(
                    user_id="legacy-user-2",
                    external_user_id="session-2",
                    source_type="legacy-session",
                    status="active",
                    created_at=fixed_ts,
                    updated_at=fixed_ts,
                ),
            )
        ),
        wallet_auth_service=WalletAuthService(
            repository=_ReadOnlyWalletRepo(
                spy,
                WalletBindingRecord(
                    wallet_binding_id="wb-2",
                    user_id="legacy-user-2",
                    wallet_type="LEGACY_SESSION",
                    signature_type="SESSION",
                    funder_address="0xabc123",
                    auth_state="UNVERIFIED",
                    mode="PAPER",
                    auth_provider="polymarket",
                    created_at=fixed_ts,
                    updated_at=fixed_ts,
                ),
            )
        ),
        permission_service=PermissionService(
            repository=_ReadOnlyPermissionRepo(
                spy,
                PermissionProfileRecord(
                    user_id="legacy-user-2",
                    allowed_markets=("MKT-A",),
                    live_enabled=False,
                    paper_enabled=True,
                    max_notional_cap=5_000.0,
                    max_positions_cap=5,
                    version="phase2-foundation",
                    updated_at=fixed_ts,
                ),
            )
        ),
        strategy_subscription_service=StrategySubscriptionService(repository=_ReadOnlySubscriptionRepo(spy)),
    )

    assert not any("repository" in name for name in vars(resolver))

    first = resolver.resolve(_seed())
    second = resolver.resolve(_seed())

    assert first == second
    assert first.execution_context.trace_id == "trace-2"
    assert spy.write_calls == []
