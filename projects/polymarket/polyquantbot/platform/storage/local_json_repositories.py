from __future__ import annotations

from dataclasses import replace

from .local_json_backend import LocalJsonBackend
from .models import (
    AuditEventRecord,
    ExecutionContextRecord,
    PermissionProfileRecord,
    StrategySubscriptionRecord,
    UserAccountRecord,
    WalletBindingRecord,
    model_to_dict,
    parse_datetime,
    utc_now,
)
from .repositories import (
    AuditEventRepository,
    ExecutionContextRepository,
    PermissionProfileRepository,
    StrategySubscriptionRepository,
    UserAccountRepository,
    WalletBindingRepository,
)


class LocalJsonUserAccountRepository(UserAccountRepository):
    def __init__(self, backend: LocalJsonBackend) -> None:
        self._backend = backend

    def get_by_user_id(self, *, user_id: str) -> UserAccountRecord | None:
        payload = self._backend.load_namespace("accounts").get(user_id)
        if payload is None:
            return None
        return UserAccountRecord(
            user_id=payload["user_id"],
            external_user_id=payload["external_user_id"],
            source_type=payload["source_type"],
            status=payload["status"],
            created_at=parse_datetime(payload["created_at"]),
            updated_at=parse_datetime(payload["updated_at"]),
        )

    def upsert(self, record: UserAccountRecord) -> UserAccountRecord:
        namespace = self._backend.load_namespace("accounts")
        namespace[record.user_id] = model_to_dict(record)
        self._backend.save_namespace("accounts", namespace)
        return record


class LocalJsonWalletBindingRepository(WalletBindingRepository):
    def __init__(self, backend: LocalJsonBackend) -> None:
        self._backend = backend

    def get_by_id(self, *, wallet_binding_id: str) -> WalletBindingRecord | None:
        payload = self._backend.load_namespace("wallet_bindings").get(wallet_binding_id)
        if payload is None:
            return None
        return WalletBindingRecord(
            wallet_binding_id=payload["wallet_binding_id"],
            user_id=payload["user_id"],
            wallet_type=payload["wallet_type"],
            signature_type=payload["signature_type"],
            funder_address=payload["funder_address"],
            auth_state=payload["auth_state"],
            mode=payload["mode"],
            auth_provider=payload["auth_provider"],
            created_at=parse_datetime(payload["created_at"]),
            updated_at=parse_datetime(payload["updated_at"]),
        )

    def upsert(self, record: WalletBindingRecord) -> WalletBindingRecord:
        namespace = self._backend.load_namespace("wallet_bindings")
        namespace[record.wallet_binding_id] = model_to_dict(record)
        self._backend.save_namespace("wallet_bindings", namespace)
        return record


class LocalJsonPermissionProfileRepository(PermissionProfileRepository):
    def __init__(self, backend: LocalJsonBackend) -> None:
        self._backend = backend

    def get_by_user_id(self, *, user_id: str) -> PermissionProfileRecord | None:
        payload = self._backend.load_namespace("permission_profiles").get(user_id)
        if payload is None:
            return None
        return PermissionProfileRecord(
            user_id=payload["user_id"],
            allowed_markets=tuple(payload["allowed_markets"]),
            live_enabled=payload["live_enabled"],
            paper_enabled=payload["paper_enabled"],
            max_notional_cap=payload["max_notional_cap"],
            max_positions_cap=payload["max_positions_cap"],
            version=payload["version"],
            updated_at=parse_datetime(payload["updated_at"]),
        )

    def upsert(self, record: PermissionProfileRecord) -> PermissionProfileRecord:
        namespace = self._backend.load_namespace("permission_profiles")
        namespace[record.user_id] = model_to_dict(record)
        self._backend.save_namespace("permission_profiles", namespace)
        return record


class LocalJsonStrategySubscriptionRepository(StrategySubscriptionRepository):
    def __init__(self, backend: LocalJsonBackend) -> None:
        self._backend = backend

    def list_by_user_id(self, *, user_id: str) -> tuple[StrategySubscriptionRecord, ...]:
        namespace = self._backend.load_namespace("strategy_subscriptions")
        rows: list[StrategySubscriptionRecord] = []
        for payload in namespace.values():
            if payload.get("user_id") == user_id:
                rows.append(
                    StrategySubscriptionRecord(
                        subscription_id=payload["subscription_id"],
                        user_id=payload["user_id"],
                        strategy_id=payload["strategy_id"],
                        enabled=payload["enabled"],
                        risk_budget=payload["risk_budget"],
                        created_at=parse_datetime(payload["created_at"]),
                        updated_at=parse_datetime(payload["updated_at"]),
                    )
                )
        rows.sort(key=lambda item: item.subscription_id)
        return tuple(rows)

    def upsert(self, record: StrategySubscriptionRecord) -> StrategySubscriptionRecord:
        namespace = self._backend.load_namespace("strategy_subscriptions")
        namespace[record.subscription_id] = model_to_dict(record)
        self._backend.save_namespace("strategy_subscriptions", namespace)
        return record


class LocalJsonExecutionContextRepository(ExecutionContextRepository):
    def __init__(self, backend: LocalJsonBackend) -> None:
        self._backend = backend

    def get_by_trace_id(self, *, trace_id: str) -> ExecutionContextRecord | None:
        namespace = self._backend.load_namespace("execution_contexts")
        for payload in namespace.values():
            if payload.get("trace_id") == trace_id:
                return ExecutionContextRecord(
                    context_id=payload["context_id"],
                    user_id=payload["user_id"],
                    wallet_binding_id=payload["wallet_binding_id"],
                    mode=payload["mode"],
                    allowed_markets=tuple(payload["allowed_markets"]),
                    permission_version=payload["permission_version"],
                    risk_profile_id=payload["risk_profile_id"],
                    trace_id=payload["trace_id"],
                    created_at=parse_datetime(payload["created_at"]),
                )
        return None

    def save(self, record: ExecutionContextRecord) -> ExecutionContextRecord:
        namespace = self._backend.load_namespace("execution_contexts")
        namespace[record.context_id] = model_to_dict(record)
        self._backend.save_namespace("execution_contexts", namespace)
        return record


class LocalJsonAuditEventRepository(AuditEventRepository):
    def __init__(self, backend: LocalJsonBackend) -> None:
        self._backend = backend

    def append(self, record: AuditEventRecord) -> AuditEventRecord:
        namespace = self._backend.load_namespace("audit_events")
        namespace[record.event_id] = model_to_dict(record)
        self._backend.save_namespace("audit_events", namespace)
        return record

    def list_by_trace_id(self, *, trace_id: str) -> tuple[AuditEventRecord, ...]:
        namespace = self._backend.load_namespace("audit_events")
        rows: list[AuditEventRecord] = []
        for payload in namespace.values():
            if payload.get("trace_id") == trace_id:
                rows.append(
                    AuditEventRecord(
                        event_id=payload["event_id"],
                        user_id=payload["user_id"],
                        category=payload["category"],
                        action=payload["action"],
                        status=payload["status"],
                        trace_id=payload["trace_id"],
                        payload_json=payload["payload_json"],
                        created_at=parse_datetime(payload["created_at"]),
                    )
                )
        rows.sort(key=lambda item: item.created_at)
        return tuple(rows)


class NullAuditEventRepository(AuditEventRepository):
    def append(self, record: AuditEventRecord) -> AuditEventRecord:
        return replace(record, created_at=record.created_at or utc_now())

    def list_by_trace_id(self, *, trace_id: str) -> tuple[AuditEventRecord, ...]:
        return ()
