"""Minimal multi-user schemas for Crusader foundation services."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ScopeStatus = Literal["active", "inactive"]
WalletStatus = Literal["linked", "unlinked"]


class UserCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    display_name: str | None = None


class UserRecord(BaseModel):
    user_id: str
    tenant_id: str
    external_id: str
    display_name: str | None = None
    status: ScopeStatus = "active"
    created_at: datetime


class UserSettingsRecord(BaseModel):
    settings_id: str
    tenant_id: str
    user_id: str
    timezone: str = "UTC"
    notifications_enabled: bool = True
    created_at: datetime


class AccountCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class AccountRecord(BaseModel):
    account_id: str
    tenant_id: str
    user_id: str
    label: str
    status: ScopeStatus = "active"
    created_at: datetime


class WalletCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    address: str = Field(min_length=1)


class WalletRecord(BaseModel):
    wallet_id: str
    tenant_id: str
    user_id: str
    account_id: str
    address: str
    status: WalletStatus = "linked"
    created_at: datetime


class ScopeContext(BaseModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class OwnershipCheckResult(BaseModel):
    resource_type: str
    resource_id: str
    owner_user_id: str
    owner_tenant_id: str
    is_owner: bool


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
