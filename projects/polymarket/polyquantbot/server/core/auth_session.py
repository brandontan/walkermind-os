"""Trusted auth/session scope derivation primitives."""
from __future__ import annotations

from datetime import datetime

from projects.polymarket.polyquantbot.server.schemas.auth_session import SessionContext, TrustedSessionHeaders
from projects.polymarket.polyquantbot.server.schemas.multi_user import ScopeContext


class AuthSessionError(RuntimeError):
    """Raised when identity/session scope cannot be trusted."""


def derive_authenticated_scope(
    headers: TrustedSessionHeaders,
    session: SessionContext,
    now: datetime,
) -> ScopeContext:
    if session.status != "active":
        raise AuthSessionError(f"session is not active: {session.status}")
    if session.expires_at <= now:
        raise AuthSessionError("session has expired")
    if session.session_id != headers.session_id:
        raise AuthSessionError("session_id mismatch")
    if session.tenant_id != headers.tenant_id:
        raise AuthSessionError("tenant_id mismatch")
    if session.user_id != headers.user_id:
        raise AuthSessionError("user_id mismatch")

    return ScopeContext(tenant_id=session.tenant_id, user_id=session.user_id)
