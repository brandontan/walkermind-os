from __future__ import annotations

from typing import Protocol

from .models import (
    AuditEventRecord,
    ExecutionContextRecord,
    PermissionProfileRecord,
    StrategySubscriptionRecord,
    UserAccountRecord,
    WalletBindingRecord,
)


class UserAccountRepository(Protocol):
    def get_by_user_id(self, *, user_id: str) -> UserAccountRecord | None: ...

    def upsert(self, record: UserAccountRecord) -> UserAccountRecord: ...


class WalletBindingRepository(Protocol):
    def get_by_id(self, *, wallet_binding_id: str) -> WalletBindingRecord | None: ...

    def upsert(self, record: WalletBindingRecord) -> WalletBindingRecord: ...


class PermissionProfileRepository(Protocol):
    def get_by_user_id(self, *, user_id: str) -> PermissionProfileRecord | None: ...

    def upsert(self, record: PermissionProfileRecord) -> PermissionProfileRecord: ...


class StrategySubscriptionRepository(Protocol):
    def list_by_user_id(self, *, user_id: str) -> tuple[StrategySubscriptionRecord, ...]: ...

    def upsert(self, record: StrategySubscriptionRecord) -> StrategySubscriptionRecord: ...


class ExecutionContextRepository(Protocol):
    def get_by_trace_id(self, *, trace_id: str) -> ExecutionContextRecord | None: ...

    def save(self, record: ExecutionContextRecord) -> ExecutionContextRecord: ...


class AuditEventRepository(Protocol):
    def append(self, record: AuditEventRecord) -> AuditEventRecord: ...

    def list_by_trace_id(self, *, trace_id: str) -> tuple[AuditEventRecord, ...]: ...
