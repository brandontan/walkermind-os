"""Wallet lifecycle domain model — Priority 4 foundation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class WalletLifecycleStatus(str, Enum):
    UNLINKED = "unlinked"
    LINKED = "linked"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    BLOCKED = "blocked"


# (from_status, to_status) → requires_admin
_TRANSITIONS: dict[tuple[WalletLifecycleStatus, WalletLifecycleStatus], bool] = {
    (WalletLifecycleStatus.UNLINKED, WalletLifecycleStatus.LINKED): False,
    (WalletLifecycleStatus.LINKED, WalletLifecycleStatus.ACTIVE): False,
    (WalletLifecycleStatus.LINKED, WalletLifecycleStatus.DEACTIVATED): False,
    (WalletLifecycleStatus.ACTIVE, WalletLifecycleStatus.DEACTIVATED): False,
    (WalletLifecycleStatus.DEACTIVATED, WalletLifecycleStatus.LINKED): False,
    (WalletLifecycleStatus.ACTIVE, WalletLifecycleStatus.BLOCKED): True,
    (WalletLifecycleStatus.LINKED, WalletLifecycleStatus.BLOCKED): True,
    (WalletLifecycleStatus.BLOCKED, WalletLifecycleStatus.LINKED): True,
}

_ADMIN_ONLY: frozenset[tuple[WalletLifecycleStatus, WalletLifecycleStatus]] = frozenset(
    k for k, admin in _TRANSITIONS.items() if admin
)


def is_valid_transition(
    from_status: WalletLifecycleStatus,
    to_status: WalletLifecycleStatus,
) -> bool:
    return (from_status, to_status) in _TRANSITIONS


def requires_admin(
    from_status: WalletLifecycleStatus,
    to_status: WalletLifecycleStatus,
) -> bool:
    return (from_status, to_status) in _ADMIN_ONLY


@dataclass(frozen=True)
class WalletLifecycleRecord:
    wallet_id: str
    tenant_id: str
    user_id: str
    address: str
    status: WalletLifecycleStatus
    previous_status: Optional[WalletLifecycleStatus]
    status_changed_at: datetime
    changed_by: str
    created_at: datetime
    chain_id: str = "polygon"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WalletAuditEntry:
    log_id: str
    wallet_id: str
    from_status: Optional[WalletLifecycleStatus]
    to_status: WalletLifecycleStatus
    changed_at: datetime
    changed_by: str
    reason: str


@dataclass(frozen=True)
class WalletLifecycleTransitionResult:
    outcome: str  # ok | invalid_transition | not_found | privilege_error | duplicate_address | stale_recovery | error
    wallet: Optional[WalletLifecycleRecord]
    audit_entry: Optional[WalletAuditEntry]
    reason: str


def new_wallet_id() -> str:
    return f"wlc_{uuid4().hex[:12]}"


def new_log_id() -> str:
    return f"wal_{uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
