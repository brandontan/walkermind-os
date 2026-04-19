"""Minimal API foundation routes for user/account/wallet ownership boundaries."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from projects.polymarket.polyquantbot.server.api.auth_session_dependencies import get_authenticated_scope
from projects.polymarket.polyquantbot.server.core.auth_session import AuthSessionError
from projects.polymarket.polyquantbot.server.core.scope import ScopeResolutionError
from projects.polymarket.polyquantbot.server.schemas.auth_session import SessionCreateRequest
from projects.polymarket.polyquantbot.server.schemas.multi_user import AccountCreate, ScopeContext, UserCreate, WalletCreate
from projects.polymarket.polyquantbot.server.services.account_service import AccountService
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.services.wallet_service import WalletService


def build_multi_user_router(
    user_service: UserService,
    account_service: AccountService,
    wallet_service: WalletService,
    auth_session_service: AuthSessionService,
) -> APIRouter:
    router = APIRouter(prefix="/foundation", tags=["multi-user-foundation"])

    @router.post("/users")
    async def create_user(payload: UserCreate) -> dict[str, object]:
        user, settings = user_service.create_user(payload)
        return {"user": user.model_dump(), "user_settings": settings.model_dump()}

    @router.post("/sessions")
    async def create_session(payload: SessionCreateRequest) -> dict[str, object]:
        try:
            result = auth_session_service.issue_session(payload)
        except ScopeResolutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AuthSessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.model_dump()

    @router.get("/auth/scope")
    async def get_scope(scope=Depends(get_authenticated_scope)) -> dict[str, object]:
        return {"scope": scope.model_dump()}

    @router.post("/sessions/{session_id}/revoke")
    async def revoke_session(session_id: str) -> dict[str, object]:
        try:
            session = auth_session_service.revoke_session(session_id=session_id)
        except AuthSessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"session": session.model_dump()}

    @router.post("/accounts")
    async def create_account(payload: AccountCreate) -> dict[str, object]:
        try:
            account = account_service.create_account(payload)
        except ScopeResolutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"account": account.model_dump()}

    @router.post("/wallets")
    async def create_wallet(payload: WalletCreate) -> dict[str, object]:
        try:
            wallet = wallet_service.create_wallet(payload)
        except ScopeResolutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"wallet": wallet.model_dump()}

    @router.get("/wallets/{wallet_id}")
    async def get_wallet(wallet_id: str, auth_scope=Depends(get_authenticated_scope)) -> dict[str, object]:
        try:
            scope = ScopeContext(tenant_id=auth_scope.tenant_id, user_id=auth_scope.user_id)
            wallet = wallet_service.get_wallet_for_scope(scope=scope, wallet_id=wallet_id)
        except ScopeResolutionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"wallet": wallet.model_dump()}

    return router
