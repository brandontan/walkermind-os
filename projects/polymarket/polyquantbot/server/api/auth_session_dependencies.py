"""FastAPI dependencies for trusted auth/session scope derivation.

Permission model (P8-D boundary):
  - User routes:     get_authenticated_scope() — reads X-Session-Id / X-Auth-* trusted
                     headers set by the session service; binds requests to tenant+user scope.
  - Operator routes: _require_operator_api_key() in public_beta_routes.py — key-based gate
                     for capital-mode and admin surfaces (system-wide, not per-user).
  - Portfolio routes: hardcode tenant_id=system / user_id=paper_user (pre-P9 known issue).
                     Full per-user route binding is deferred to multi-user rollout (Priority 9).
"""
from __future__ import annotations

from fastapi import Header, HTTPException, Request

from projects.polymarket.polyquantbot.server.core.auth_session import AuthSessionError
from projects.polymarket.polyquantbot.server.schemas.auth_session import AuthenticatedScope, TrustedSessionHeaders
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService


def get_authenticated_scope(
    request: Request,
    x_session_id: str = Header(alias="X-Session-Id"),
    x_auth_tenant_id: str = Header(alias="X-Auth-Tenant-Id"),
    x_auth_user_id: str = Header(alias="X-Auth-User-Id"),
) -> AuthenticatedScope:
    service: AuthSessionService = request.app.state.auth_session_service
    headers = TrustedSessionHeaders(
        session_id=x_session_id,
        tenant_id=x_auth_tenant_id,
        user_id=x_auth_user_id,
    )
    try:
        return service.get_authenticated_scope(headers=headers)
    except AuthSessionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
