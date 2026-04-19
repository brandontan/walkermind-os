"""Storage-model foundation for multi-user user/account/wallet state."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserModel:
    user_id: str
    tenant_id: str
    external_id: str
    display_name: str | None
    status: str
    created_at: str


@dataclass(frozen=True)
class UserSettingsModel:
    settings_id: str
    tenant_id: str
    user_id: str
    timezone: str
    notifications_enabled: bool
    created_at: str


@dataclass(frozen=True)
class AccountModel:
    account_id: str
    tenant_id: str
    user_id: str
    label: str
    status: str
    created_at: str


@dataclass(frozen=True)
class WalletModel:
    wallet_id: str
    tenant_id: str
    user_id: str
    account_id: str
    address: str
    status: str
    created_at: str
