"""Telegram activation-to-session issuance foundation service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from projects.polymarket.polyquantbot.server.core.auth_session import AuthSessionError
from projects.polymarket.polyquantbot.server.schemas.auth_session import SessionCreateRequest
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService
from projects.polymarket.polyquantbot.server.services.telegram_onboarding_service import (
    TELEGRAM_EXTERNAL_ID_PREFIX,
)
from projects.polymarket.polyquantbot.server.services.user_service import UserService

log = structlog.get_logger(__name__)

TelegramSessionIssuanceOutcome = Literal[
    "session_issued",
    "already_active_session_issued",
    "rejected",
    "error",
]


@dataclass(frozen=True)
class TelegramSessionIssuanceResult:
    outcome: TelegramSessionIssuanceOutcome
    tenant_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    detail: str | None = None


class TelegramSessionIssuanceService:
    """Narrow Telegram activation-state gate + backend session issuance.

    Allowed paths:
    - pending_confirmation -> active + session_issued
    - active -> already_active_session_issued
    Rejected paths:
    - user not linked / invalid inputs
    """

    def __init__(
        self,
        user_service: UserService,
        auth_session_service: AuthSessionService,
    ) -> None:
        self._user_service = user_service
        self._auth_session_service = auth_session_service

    def issue(self, telegram_user_id: str, tenant_id: str, ttl_seconds: int = 1800) -> TelegramSessionIssuanceResult:
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramSessionIssuanceResult(
                outcome="rejected",
                detail="telegram_user_id must not be empty",
            )
        if not tenant_id or not tenant_id.strip():
            return TelegramSessionIssuanceResult(
                outcome="rejected",
                detail="tenant_id must not be empty",
            )

        external_id = f"{TELEGRAM_EXTERNAL_ID_PREFIX}{telegram_user_id}"
        try:
            user = self._user_service.get_user_by_external_id(tenant_id=tenant_id, external_id=external_id)
            if user is None:
                return TelegramSessionIssuanceResult(
                    outcome="rejected",
                    detail="user is not linked",
                )

            settings = self._user_service.get_user_settings(user.user_id)
            if settings is None:
                return TelegramSessionIssuanceResult(
                    outcome="error",
                    detail="user settings not found",
                )

            outcome: TelegramSessionIssuanceOutcome = "already_active_session_issued"
            if settings.activation_status != "active":
                updated = self._user_service.set_activation_status(
                    user_id=user.user_id,
                    activation_status="active",
                )
                if updated is None:
                    return TelegramSessionIssuanceResult(
                        outcome="error",
                        detail="activation persistence failed",
                    )
                outcome = "session_issued"

            session = self._auth_session_service.issue_session(
                SessionCreateRequest(
                    tenant_id=user.tenant_id,
                    user_id=user.user_id,
                    auth_method="telegram",
                    ttl_seconds=ttl_seconds,
                )
            )

            log.info(
                "crusaderbot_telegram_session_issuance_success",
                outcome=outcome,
                tenant_id=user.tenant_id,
                user_id=user.user_id,
                telegram_user_id=telegram_user_id,
                session_id=session.session.session_id,
            )
            return TelegramSessionIssuanceResult(
                outcome=outcome,
                tenant_id=user.tenant_id,
                user_id=user.user_id,
                session_id=session.session.session_id,
            )
        except AuthSessionError as exc:
            log.error(
                "crusaderbot_telegram_session_issuance_auth_error",
                tenant_id=tenant_id,
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramSessionIssuanceResult(
                outcome="error",
                detail=str(exc),
            )
        except Exception as exc:
            log.error(
                "crusaderbot_telegram_session_issuance_error",
                tenant_id=tenant_id,
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramSessionIssuanceResult(
                outcome="error",
                detail=str(exc),
            )
