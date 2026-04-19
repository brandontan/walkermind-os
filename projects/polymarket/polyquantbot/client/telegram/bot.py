"""Telegram bootstrap surface for CrusaderBot."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import structlog

from projects.polymarket.polyquantbot.client.telegram.backend_client import CrusaderBackendClient
from projects.polymarket.polyquantbot.client.telegram.dispatcher import TelegramDispatcher
from projects.polymarket.polyquantbot.client.telegram.runtime import (
    HttpTelegramAdapter,
    run_polling_loop,
)

log = structlog.get_logger(__name__)

_DEFAULT_BACKEND_URL = "http://localhost:8080"


@dataclass(frozen=True)
class TelegramBotSettings:
    app_name: str = "CrusaderBot"
    startup_mode: str = "strict"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    backend_base_url: str = _DEFAULT_BACKEND_URL
    staging_tenant_id: str = "staging"
    staging_user_id: str = "staging"

    @classmethod
    def from_env(cls) -> "TelegramBotSettings":
        startup_mode = os.getenv("CRUSADER_STARTUP_MODE", "strict").strip().lower() or "strict"
        if startup_mode != "strict":
            raise RuntimeError(
                "CRUSADER_STARTUP_MODE must be 'strict' for the current Telegram bootstrap contract."
            )

        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        backend_url = (
            os.getenv("CRUSADER_BACKEND_URL", _DEFAULT_BACKEND_URL).strip() or _DEFAULT_BACKEND_URL
        )
        staging_tenant_id = (
            os.getenv("CRUSADER_STAGING_TENANT_ID", "staging").strip() or "staging"
        )
        staging_user_id = (
            os.getenv("CRUSADER_STAGING_USER_ID", "staging").strip() or "staging"
        )

        return cls(
            startup_mode=startup_mode,
            telegram_token=token,
            telegram_chat_id=chat_id,
            backend_base_url=backend_url,
            staging_tenant_id=staging_tenant_id,
            staging_user_id=staging_user_id,
        )


def validate_bot_environment(settings: TelegramBotSettings) -> list[str]:
    errors: list[str] = []
    if not settings.telegram_token:
        errors.append("TELEGRAM_BOT_TOKEN is required for the Telegram runtime surface.")
    return errors


async def run_bot() -> None:
    settings = TelegramBotSettings.from_env()
    validation_errors = validate_bot_environment(settings)

    if validation_errors:
        log.error(
            "crusaderbot_telegram_startup_validation_failed",
            errors=validation_errors,
            startup_mode=settings.startup_mode,
        )
        raise RuntimeError("; ".join(validation_errors))

    backend = CrusaderBackendClient(
        base_url=settings.backend_base_url,
        identity_tenant_id=settings.staging_tenant_id,
    )
    dispatcher = TelegramDispatcher(backend=backend)
    adapter = HttpTelegramAdapter(token=settings.telegram_token)

    log.info(
        "crusaderbot_telegram_bootstrap_ready",
        runtime="client.telegram.bot",
        app_name=settings.app_name,
        chat_id_configured=bool(settings.telegram_chat_id),
        backend_base_url=settings.backend_base_url,
        dispatcher="client.telegram.dispatcher.TelegramDispatcher",
        adapter="client.telegram.runtime.HttpTelegramAdapter",
        identity_resolution="backend",
        registered_commands=["/start", "/mode", "/autotrade", "/positions", "/pnl", "/risk", "/status", "/markets", "/market360", "/social", "/kill"],
        phase="8.3-public-paper-beta",
        staging_tenant_id=settings.staging_tenant_id,
        staging_user_id=settings.staging_user_id,
    )

    await run_polling_loop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=backend,
        onboarding_initiator=backend,
        activation_confirmer=backend,
        staging_tenant_id=settings.staging_tenant_id,
        staging_user_id=settings.staging_user_id,
    )


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
