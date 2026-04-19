"""Minimal auth/session foundation service for trusted scope derivation."""
from __future__ import annotations

from datetime import timedelta

from projects.polymarket.polyquantbot.server.core.auth_session import AuthSessionError, derive_authenticated_scope
from projects.polymarket.polyquantbot.server.schemas.auth_session import (
    AuthIdentityContext,
    AuthenticatedScope,
    SessionContext,
    SessionCreateRequest,
    SessionIssueResponse,
    TrustedSessionHeaders,
)
from projects.polymarket.polyquantbot.server.schemas.multi_user import new_id, now_utc
from projects.polymarket.polyquantbot.server.storage.in_memory_store import InMemoryMultiUserStore


class AuthSessionService:
    def __init__(self, store: InMemoryMultiUserStore) -> None:
        self._store = store

    def issue_session(self, payload: SessionCreateRequest) -> SessionIssueResponse:
        user = self._store.get_user(payload.user_id)
        if user is None:
            raise AuthSessionError(f"user not found: {payload.user_id}")
        if user.tenant_id != payload.tenant_id:
            raise AuthSessionError("session tenant_id must match owner user tenant_id")

        issued_at = now_utc()
        session = SessionContext(
            session_id=new_id("sess"),
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            auth_method=payload.auth_method,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=payload.ttl_seconds),
            status="active",
        )
        self._store.put_session(session)

        identity = AuthIdentityContext(
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            auth_method=payload.auth_method,
            authenticated_at=issued_at,
        )
        scope = AuthenticatedScope(
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            session_id=session.session_id,
            auth_method=payload.auth_method,
        )
        return SessionIssueResponse(identity=identity, session=session, scope=scope)

    def get_authenticated_scope(self, headers: TrustedSessionHeaders) -> AuthenticatedScope:
        session = self._store.get_session(headers.session_id)
        if session is None:
            raise AuthSessionError(f"session not found: {headers.session_id}")

        scope = derive_authenticated_scope(headers=headers, session=session, now=now_utc())
        return AuthenticatedScope(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=session.session_id,
            auth_method=session.auth_method,
        )
