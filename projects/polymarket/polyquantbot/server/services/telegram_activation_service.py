"""Telegram confirmation/activation foundation service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from projects.polymarket.polyquantbot.server.services.telegram_identity_service import TELEGRAM_EXTERNAL_ID_PREFIX
from projects.polymarket.polyquantbot.server.services.user_service import UserService

log = structlog.get_logger(__name__)

TelegramActivationOutcome = Literal["activated", "already_active", "rejected", "error"]


@dataclass(frozen=True)
class TelegramActivationResult:
    outcome: TelegramActivationOutcome
    tenant_id: str | None = None
    user_id: str | None = None
    detail: str | None = None


class TelegramActivationService:
    """Minimal confirmation/activation boundary for Telegram-linked users."""

    def __init__(self, user_service: UserService) -> None:
        self._user_service = user_service

    def confirm(self, telegram_user_id: str, tenant_id: str) -> TelegramActivationResult:
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramActivationResult(
                outcome="rejected",
                detail="telegram_user_id must not be empty",
            )
        if not tenant_id or not tenant_id.strip():
            return TelegramActivationResult(
                outcome="rejected",
                detail="tenant_id must not be empty",
            )

        external_id = f"{TELEGRAM_EXTERNAL_ID_PREFIX}{telegram_user_id}"
        try:
            user = self._user_service.get_user_by_external_id(tenant_id=tenant_id, external_id=external_id)
            if user is None:
                return TelegramActivationResult(
                    outcome="rejected",
                    detail="user is not linked",
                )

            settings = self._user_service.get_user_settings(user.user_id)
            if settings is None:
                return TelegramActivationResult(
                    outcome="error",
                    detail="user settings not found",
                )

            if settings.activation_status == "active":
                return TelegramActivationResult(
                    outcome="already_active",
                    tenant_id=user.tenant_id,
                    user_id=user.user_id,
                )

            updated = self._user_service.set_activation_status(
                user_id=user.user_id,
                activation_status="active",
            )
            if updated is None:
                return TelegramActivationResult(
                    outcome="error",
                    detail="activation persistence failed",
                )

            log.info(
                "crusaderbot_telegram_activation_confirmed",
                tenant_id=user.tenant_id,
                user_id=user.user_id,
                telegram_user_id=telegram_user_id,
            )
            return TelegramActivationResult(
                outcome="activated",
                tenant_id=user.tenant_id,
                user_id=user.user_id,
            )
        except Exception as exc:
            log.error(
                "crusaderbot_telegram_activation_error",
                tenant_id=tenant_id,
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramActivationResult(
                outcome="error",
                detail=str(exc),
            )
