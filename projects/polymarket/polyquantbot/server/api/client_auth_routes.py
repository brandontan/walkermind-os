"""Client auth handoff and wallet-link authenticated routes."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from projects.polymarket.polyquantbot.server.api.auth_session_dependencies import get_authenticated_scope
from projects.polymarket.polyquantbot.server.core.auth_session import AuthSessionError
from projects.polymarket.polyquantbot.server.core.client_auth_handoff import ClientHandoffContract, validate_client_handoff
from projects.polymarket.polyquantbot.server.core.scope import ScopeResolutionError
from projects.polymarket.polyquantbot.server.schemas.auth_session import AuthMethod, SessionCreateRequest
from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkCreateRequest
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService
from projects.polymarket.polyquantbot.server.services.wallet_link_service import WalletLinkService


class ClientHandoffRequestBody(BaseModel):
    client_type: str = Field(min_length=1)
    client_identity_claim: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    ttl_seconds: int = Field(default=1800, ge=60, le=86400)


def build_client_auth_router(
    auth_session_service: AuthSessionService,
    wallet_link_service: WalletLinkService,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["client-auth"])

    @router.post("/handoff")
    async def client_handoff(body: ClientHandoffRequestBody) -> dict[str, object]:
        """Trusted client identity handoff into backend session.

        Accepts a client_type (telegram/web) and a client_identity_claim (e.g. telegram_user_id).
        Validates structural contract, then issues a session via the auth session service.
        Does NOT perform cryptographic identity verification — that is a future production gate.
        """
        contract = ClientHandoffContract(
            client_type=body.client_type,
            client_identity_claim=body.client_identity_claim,
            tenant_id=body.tenant_id,
            user_id=body.user_id,
            ttl_seconds=body.ttl_seconds,
        )
        validation = validate_client_handoff(contract)
        if validation.outcome != "valid":
            raise HTTPException(status_code=400, detail=validation.detail)

        session_request = SessionCreateRequest(
            tenant_id=body.tenant_id,
            user_id=body.user_id,
            auth_method=validation.auth_method,  # type: ignore[arg-type]
            ttl_seconds=body.ttl_seconds,
        )
        try:
            result = auth_session_service.issue_session(session_request)
        except (AuthSessionError, ScopeResolutionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.model_dump()

    @router.post("/wallet-links")
    async def create_wallet_link(
        body: WalletLinkCreateRequest,
        auth_scope=Depends(get_authenticated_scope),
    ) -> dict[str, object]:
        record = wallet_link_service.create_link(scope=auth_scope, request=body)
        return {"wallet_link": record.model_dump()}

    @router.get("/wallet-links")
    async def list_wallet_links(
        auth_scope=Depends(get_authenticated_scope),
    ) -> dict[str, object]:
        links = wallet_link_service.list_links(scope=auth_scope)
        return {"wallet_links": [r.model_dump() for r in links]}

    return router
