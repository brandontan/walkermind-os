"""Minimal API foundation routes for user/account/wallet ownership boundaries."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from projects.polymarket.polyquantbot.server.core.scope import ScopeResolutionError, resolve_scope
from projects.polymarket.polyquantbot.server.schemas.multi_user import AccountCreate, ScopeContext, UserCreate, WalletCreate
from projects.polymarket.polyquantbot.server.services.account_service import AccountService
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.services.wallet_service import WalletService


def build_multi_user_router(
    user_service: UserService,
    account_service: AccountService,
    wallet_service: WalletService,
) -> APIRouter:
    router = APIRouter(prefix="/foundation", tags=["multi-user-foundation"])

    @router.post("/users")
    async def create_user(payload: UserCreate) -> dict[str, object]:
        user, settings = user_service.create_user(payload)
        return {"user": user.model_dump(), "user_settings": settings.model_dump()}

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
    async def get_wallet(
        wallet_id: str,
        x_tenant_id: str = Header(alias="X-Tenant-Id"),
        x_user_id: str = Header(alias="X-User-Id"),
    ) -> dict[str, object]:
        try:
            scope: ScopeContext = resolve_scope(tenant_id=x_tenant_id, user_id=x_user_id)
            wallet = wallet_service.get_wallet_for_scope(scope=scope, wallet_id=wallet_id)
        except ScopeResolutionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"wallet": wallet.model_dump()}

    return router
