"""Telegram identity resolution service — maps telegram_user_id to backend user scope."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from projects.polymarket.polyquantbot.server.services.user_service import UserService

log = structlog.get_logger(__name__)

TelegramIdentityOutcome = Literal["resolved", "not_found", "error"]

TELEGRAM_EXTERNAL_ID_PREFIX = "tg_"


@dataclass(frozen=True)
class TelegramIdentityResolution:
    """Result of resolving a Telegram user_id to backend user scope.

    outcome: resolved   -> tenant_id and user_id are populated with real backend scope
    outcome: not_found  -> no user registered with this telegram_user_id in the tenant
    outcome: error      -> backend lookup failed; error_detail carries reason
    """

    outcome: TelegramIdentityOutcome
    tenant_id: str | None = None
    user_id: str | None = None
    error_detail: str | None = None


class TelegramIdentityService:
    """Resolves inbound Telegram from_user_id to backend tenant/user scope.

    Looks up users by external_id = 'tg_{telegram_user_id}' within the given tenant.
    Returns a typed resolution outcome: resolved, not_found, or error.

    This is a pre-auth identity lookup — it does not issue sessions and does not
    perform cryptographic verification. Full account-link UX is a follow-up lane.
    """

    def __init__(self, user_service: UserService) -> None:
        self._user_service = user_service

    def resolve(self, telegram_user_id: str, tenant_id: str) -> TelegramIdentityResolution:
        """Resolve a Telegram user ID to backend user scope.

        Constructs external_id = 'tg_{telegram_user_id}' and looks up the user
        in the given tenant. Returns resolved/not_found/error outcome.
        """
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramIdentityResolution(
                outcome="error", error_detail="empty telegram_user_id"
            )
        if not tenant_id or not tenant_id.strip():
            return TelegramIdentityResolution(
                outcome="error", error_detail="empty tenant_id"
            )

        external_id = f"{TELEGRAM_EXTERNAL_ID_PREFIX}{telegram_user_id}"
        try:
            user = self._user_service.get_user_by_external_id(tenant_id, external_id)
        except Exception as exc:
            log.error(
                "telegram_identity_lookup_error",
                telegram_user_id=telegram_user_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return TelegramIdentityResolution(outcome="error", error_detail=str(exc))

        if user is None:
            log.info(
                "telegram_identity_not_found",
                telegram_user_id=telegram_user_id,
                tenant_id=tenant_id,
                external_id=external_id,
            )
            return TelegramIdentityResolution(outcome="not_found")

        log.info(
            "telegram_identity_resolved",
            telegram_user_id=telegram_user_id,
            user_id=user.user_id,
            tenant_id=user.tenant_id,
        )
        return TelegramIdentityResolution(
            outcome="resolved",
            tenant_id=user.tenant_id,
            user_id=user.user_id,
        )
