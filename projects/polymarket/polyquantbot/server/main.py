"""CrusaderBot FastAPI control-plane runtime."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from projects.polymarket.polyquantbot.server.api.client_auth_routes import build_client_auth_router
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
from projects.polymarket.polyquantbot.server.services.telegram_identity_service import TelegramIdentityService
from projects.polymarket.polyquantbot.server.services.telegram_onboarding_service import TelegramOnboardingService
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.services.wallet_link_service import WalletLinkService
from projects.polymarket.polyquantbot.server.services.wallet_service import WalletService
from projects.polymarket.polyquantbot.server.storage.multi_user_store import PersistentMultiUserStore
from projects.polymarket.polyquantbot.server.storage.session_store import PersistentSessionStore
from projects.polymarket.polyquantbot.server.storage.wallet_link_store import PersistentWalletLinkStore

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

    multi_user_storage_path = Path(
        os.getenv(
            "CRUSADER_MULTI_USER_STORAGE_PATH",
            "/tmp/crusaderbot/runtime/multi_user.json",
        )
    )
    store = PersistentMultiUserStore(storage_path=multi_user_storage_path)
    user_service = UserService(store=store)
    account_service = AccountService(store=store)
    wallet_service = WalletService(store=store)
    telegram_identity_service = TelegramIdentityService(user_service=user_service)
    telegram_onboarding_service = TelegramOnboardingService(user_service=user_service)

    session_storage_path = Path(
        os.getenv(
            "CRUSADER_SESSION_STORAGE_PATH",
            "/tmp/crusaderbot/runtime/foundation_sessions.json",
        )
    )
    persistent_session_store = PersistentSessionStore(storage_path=session_storage_path)
    auth_session_service = AuthSessionService(store=store, session_store=persistent_session_store)

    wallet_link_storage_path = Path(
        os.getenv(
            "CRUSADER_WALLET_LINK_STORAGE_PATH",
            "/tmp/crusaderbot/runtime/wallet_links.json",
        )
    )
    wallet_link_store = PersistentWalletLinkStore(storage_path=wallet_link_storage_path)
    wallet_link_service = WalletLinkService(store=wallet_link_store)

    app.state.multi_user_storage_path = multi_user_storage_path
    app.state.multi_user_store = store
    app.state.telegram_identity_service = telegram_identity_service
    app.state.telegram_onboarding_service = telegram_onboarding_service
    app.state.persistent_session_store = persistent_session_store
    app.state.user_service = user_service
    app.state.account_service = account_service
    app.state.wallet_service = wallet_service
    app.state.auth_session_service = auth_session_service
    app.state.wallet_link_storage_path = wallet_link_storage_path
    app.state.wallet_link_store = wallet_link_store
    app.state.wallet_link_service = wallet_link_service

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
    app.include_router(
        build_client_auth_router(
            auth_session_service=auth_session_service,
            wallet_link_service=wallet_link_service,
            telegram_identity_service=telegram_identity_service,
            telegram_onboarding_service=telegram_onboarding_service,
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
        multi_user_storage_path=str(multi_user_storage_path),
        session_storage_path=str(session_storage_path),
        wallet_link_storage_path=str(wallet_link_storage_path),
        phase="8.11",
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
