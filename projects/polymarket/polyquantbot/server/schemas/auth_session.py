"""Auth/session schema foundation for trusted scope derivation."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AuthMethod = Literal["foundation", "telegram", "web"]
SessionStatus = Literal["active", "revoked", "expired"]


class SessionCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    auth_method: AuthMethod = "foundation"
    ttl_seconds: int = Field(default=1800, ge=60, le=86400)


class AuthIdentityContext(BaseModel):
    tenant_id: str
    user_id: str
    auth_method: AuthMethod
    authenticated_at: datetime


class SessionContext(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    auth_method: AuthMethod
    issued_at: datetime
    expires_at: datetime
    status: SessionStatus = "active"


class AuthenticatedScope(BaseModel):
    tenant_id: str
    user_id: str
    session_id: str
    auth_method: AuthMethod


class TrustedSessionHeaders(BaseModel):
    session_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class SessionIssueResponse(BaseModel):
    identity: AuthIdentityContext
    session: SessionContext
    scope: AuthenticatedScope
