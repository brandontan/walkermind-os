"""CrusaderBot FastAPI control-plane runtime."""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from projects.polymarket.polyquantbot.server.api.multi_user_foundation_routes import build_multi_user_router
from projects.polymarket.polyquantbot.server.api.routes import build_router
from projects.polymarket.polyquantbot.server.core.runtime import (
    ApiSettings,
    RuntimeState,
    run_shutdown,
    run_startup_validation,
)
from projects.polymarket.polyquantbot.server.services.account_service import AccountService
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.services.wallet_service import WalletService
from projects.polymarket.polyquantbot.server.storage.in_memory_store import InMemoryMultiUserStore

log = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    settings = ApiSettings.from_env()
    state = RuntimeState()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await run_startup_validation(settings=settings, state=state)
        try:
            yield
        finally:
            await run_shutdown(state=state)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.crusader_settings = settings
    app.state.crusader_runtime = state

    store = InMemoryMultiUserStore()
    user_service = UserService(store=store)
    account_service = AccountService(store=store)
    wallet_service = WalletService(store=store)
    auth_session_service = AuthSessionService(store=store)

    app.state.multi_user_store = store
    app.state.user_service = user_service
    app.state.account_service = account_service
    app.state.wallet_service = wallet_service
    app.state.auth_session_service = auth_session_service

    router = build_router(settings=settings, state=state)
    app.include_router(router)
    app.include_router(
        build_multi_user_router(
            user_service=user_service,
            account_service=account_service,
            wallet_service=wallet_service,
            auth_session_service=auth_session_service,
        )
    )

    @app.get("/")
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": settings.app_name,
                "status": "ok",
                "docs": "/docs",
            }
        )

    log.info(
        "crusaderbot_api_app_created",
        runtime="server.main",
        port=settings.port,
        trading_mode=settings.trading_mode,
    )
    return app


app = create_app()


def main() -> None:
    settings: ApiSettings = app.state.crusader_settings
    uvicorn.run(
        "projects.polymarket.polyquantbot.server.main:app",
        host=settings.host,
        port=settings.port,
        factory=False,
    )


if __name__ == "__main__":
    main()
