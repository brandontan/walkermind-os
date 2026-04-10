from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class UserAccountRecord:
    user_id: str
    external_user_id: str
    source_type: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WalletBindingRecord:
    wallet_binding_id: str
    user_id: str
    wallet_type: str
    signature_type: str
    funder_address: str
    auth_state: str
    mode: str
    auth_provider: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PermissionProfileRecord:
    user_id: str
    allowed_markets: tuple[str, ...]
    live_enabled: bool
    paper_enabled: bool
    max_notional_cap: float
    max_positions_cap: int
    version: str
    updated_at: datetime


@dataclass(frozen=True)
class StrategySubscriptionRecord:
    subscription_id: str
    user_id: str
    strategy_id: str
    enabled: bool
    risk_budget: float
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ExecutionContextRecord:
    context_id: str
    user_id: str
    wallet_binding_id: str
    mode: str
    allowed_markets: tuple[str, ...]
    permission_version: str
    risk_profile_id: str
    trace_id: str
    created_at: datetime


@dataclass(frozen=True)
class AuditEventRecord:
    event_id: str
    user_id: str
    category: str
    action: str
    status: str
    trace_id: str
    payload_json: dict[str, Any]
    created_at: datetime


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def model_to_dict(model: Any) -> dict[str, Any]:
    payload = asdict(model)
    for key, value in payload.items():
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
    return payload


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)
