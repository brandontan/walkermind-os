"""Telegram onboarding/account-link foundation service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from projects.polymarket.polyquantbot.server.schemas.multi_user import UserCreate
from projects.polymarket.polyquantbot.server.services.user_service import UserService

log = structlog.get_logger(__name__)

TelegramOnboardingOutcome = Literal["onboarded", "already_linked", "rejected", "error"]
TELEGRAM_EXTERNAL_ID_PREFIX = "tg_"


@dataclass(frozen=True)
class TelegramOnboardingResult:
    outcome: TelegramOnboardingOutcome
    tenant_id: str | None = None
    user_id: str | None = None
    detail: str | None = None


class TelegramOnboardingService:
    """Narrow onboarding/account-link foundation for unresolved Telegram users.

    This service intentionally performs only a minimal, truthful action:
    - if Telegram external identity already exists under tenant => already_linked
    - else create a minimal user record bound to tg_{telegram_user_id} => onboarded
    """

    def __init__(self, user_service: UserService) -> None:
        self._user_service = user_service

    def start(self, telegram_user_id: str, tenant_id: str) -> TelegramOnboardingResult:
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramOnboardingResult(
                outcome="rejected",
                detail="telegram_user_id must not be empty",
            )
        if not tenant_id or not tenant_id.strip():
            return TelegramOnboardingResult(
                outcome="rejected",
                detail="tenant_id must not be empty",
            )

        external_id = f"{TELEGRAM_EXTERNAL_ID_PREFIX}{telegram_user_id}"
        try:
            existing = self._user_service.get_user_by_external_id(
                tenant_id=tenant_id,
                external_id=external_id,
            )
            if existing is not None:
                return TelegramOnboardingResult(
                    outcome="already_linked",
                    tenant_id=existing.tenant_id,
                    user_id=existing.user_id,
                )

            created_user, _ = self._user_service.create_user(
                UserCreate(
                    tenant_id=tenant_id,
                    external_id=external_id,
                    display_name=f"tg:{telegram_user_id}",
                )
            )
            log.info(
                "crusaderbot_telegram_onboarding_user_created",
                tenant_id=tenant_id,
                user_id=created_user.user_id,
                telegram_user_id=telegram_user_id,
            )
            return TelegramOnboardingResult(
                outcome="onboarded",
                tenant_id=created_user.tenant_id,
                user_id=created_user.user_id,
            )
        except Exception as exc:
            log.error(
                "crusaderbot_telegram_onboarding_error",
                tenant_id=tenant_id,
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramOnboardingResult(
                outcome="error",
                detail=str(exc),
            )
