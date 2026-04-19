"""Client auth handoff and wallet-link authenticated routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from projects.polymarket.polyquantbot.server.api.auth_session_dependencies import get_authenticated_scope
from projects.polymarket.polyquantbot.server.core.auth_session import AuthSessionError
from projects.polymarket.polyquantbot.server.core.client_auth_handoff import ClientHandoffContract, validate_client_handoff
from projects.polymarket.polyquantbot.server.core.scope import ScopeResolutionError
from projects.polymarket.polyquantbot.server.schemas.auth_session import AuthMethod, SessionCreateRequest
from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkCreateRequest
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService
from projects.polymarket.polyquantbot.server.services.telegram_activation_service import TelegramActivationService
from projects.polymarket.polyquantbot.server.services.telegram_identity_service import TelegramIdentityService
from projects.polymarket.polyquantbot.server.services.telegram_onboarding_service import TelegramOnboardingService
from projects.polymarket.polyquantbot.server.services.telegram_session_issuance_service import (
    TelegramSessionIssuanceService,
)
from projects.polymarket.polyquantbot.server.services.wallet_link_service import (
    WalletLinkNotFoundError,
    WalletLinkOwnershipError,
    WalletLinkService,
)


class ClientHandoffRequestBody(BaseModel):
    client_type: str = Field(min_length=1)
    client_identity_claim: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    ttl_seconds: int = Field(default=1800, ge=60, le=86400)


class TelegramOnboardingStartBody(BaseModel):
    telegram_user_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class TelegramSessionIssueBody(BaseModel):
    telegram_user_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    ttl_seconds: int = Field(default=1800, ge=60, le=86400)


def build_client_auth_router(
    auth_session_service: AuthSessionService,
    wallet_link_service: WalletLinkService,
    telegram_identity_service: TelegramIdentityService,
    telegram_onboarding_service: TelegramOnboardingService,
    telegram_activation_service: TelegramActivationService,
    telegram_session_issuance_service: TelegramSessionIssuanceService,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["client-auth"])

    @router.get("/telegram-identity/{telegram_user_id}")
    async def resolve_telegram_identity(
        telegram_user_id: str,
        tenant_id: str = Query(min_length=1),
    ) -> dict[str, object]:
        """Resolve a Telegram user ID to backend tenant/user scope.

        Pre-auth identity lookup: does not require a session. Returns outcome
        resolved/not_found/error with tenant_id and user_id when resolved.
        Used by the Telegram runtime to replace staging placeholders with real
        backend user scope before command dispatch.
        """
        resolution = telegram_identity_service.resolve(
            telegram_user_id=telegram_user_id,
            tenant_id=tenant_id,
        )
        return {
            "outcome": resolution.outcome,
            "tenant_id": resolution.tenant_id,
            "user_id": resolution.user_id,
        }

    @router.post("/telegram-onboarding/start")
    async def start_telegram_onboarding(
        body: TelegramOnboardingStartBody,
    ) -> dict[str, object]:
        """Start minimal Telegram onboarding/account-link foundation."""
        result = telegram_onboarding_service.start(
            telegram_user_id=body.telegram_user_id,
            tenant_id=body.tenant_id,
        )
        return {
            "outcome": result.outcome,
            "tenant_id": result.tenant_id,
            "user_id": result.user_id,
            "detail": result.detail,
        }

    @router.post("/telegram-onboarding/confirm")
    async def confirm_telegram_onboarding(
        body: TelegramOnboardingStartBody,
    ) -> dict[str, object]:
        """Confirm/activate Telegram-linked onboarding foundation."""
        result = telegram_activation_service.confirm(
            telegram_user_id=body.telegram_user_id,
            tenant_id=body.tenant_id,
        )
        return {
            "outcome": result.outcome,
            "tenant_id": result.tenant_id,
            "user_id": result.user_id,
            "detail": result.detail,
        }

    @router.post("/telegram-onboarding/session-issue")
    async def issue_telegram_session(
        body: TelegramSessionIssueBody,
    ) -> dict[str, object]:
        """Issue Telegram session only for activated users; pending users are rejected."""
        result = telegram_session_issuance_service.issue(
            telegram_user_id=body.telegram_user_id,
            tenant_id=body.tenant_id,
            ttl_seconds=body.ttl_seconds,
        )
        return {
            "outcome": result.outcome,
            "tenant_id": result.tenant_id,
            "user_id": result.user_id,
            "session_id": result.session_id,
            "detail": result.detail,
        }

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

    @router.patch("/wallet-links/{link_id}/unlink")
    async def unlink_wallet_link(
        link_id: str,
        auth_scope=Depends(get_authenticated_scope),
    ) -> dict[str, object]:
        try:
            record = wallet_link_service.unlink_link(scope=auth_scope, link_id=link_id)
        except WalletLinkNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WalletLinkOwnershipError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"wallet_link": record.model_dump()}

    return router
