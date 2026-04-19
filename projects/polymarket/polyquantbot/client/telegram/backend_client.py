"""Thin async HTTP client bridging Telegram/Web client runtimes to CrusaderBot backend."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import httpx
import structlog

log = structlog.get_logger(__name__)

SUPPORTED_CLIENT_TYPES: frozenset[str] = frozenset({"telegram", "web"})

HandoffOutcome = Literal["issued", "rejected", "error"]
TelegramIdentityOutcome = Literal["resolved", "not_found", "error"]
TelegramOnboardingOutcome = Literal["onboarded", "already_linked", "rejected", "error"]
TelegramActivationOutcome = Literal["activated", "already_active", "rejected", "error"]
TelegramSessionIssuanceOutcome = Literal[
    "session_issued",
    "already_active_session_issued",
    "rejected",
    "error",
]


@dataclass(frozen=True)
class BackendHandoffRequest:
    client_type: str
    client_identity_claim: str
    tenant_id: str
    user_id: str
    ttl_seconds: int = 1800


@dataclass(frozen=True)
class BackendHandoffResult:
    outcome: HandoffOutcome
    session_id: str = ""
    detail: str = ""


@dataclass(frozen=True)
class TelegramIdentityResolution:
    """Client-side result of resolving a Telegram user ID to backend user scope.

    outcome: resolved   -> tenant_id and user_id carry real backend scope
    outcome: not_found  -> no registered user for this telegram_user_id in the tenant
    outcome: error      -> backend call failed or returned unexpected response
    """

    outcome: TelegramIdentityOutcome
    tenant_id: str | None = None
    user_id: str | None = None


@dataclass(frozen=True)
class TelegramOnboardingResult:
    outcome: TelegramOnboardingOutcome
    tenant_id: str | None = None
    user_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class TelegramActivationResult:
    outcome: TelegramActivationOutcome
    tenant_id: str | None = None
    user_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class TelegramSessionIssuanceResult:
    outcome: TelegramSessionIssuanceOutcome
    tenant_id: str | None = None
    user_id: str | None = None
    session_id: str = ""
    detail: str = ""


class CrusaderBackendClient:
    """Thin async HTTP client for backend handoff calls from client runtimes.

    Makes POST /auth/handoff against the CrusaderBot FastAPI backend and maps
    the HTTP response to a typed BackendHandoffResult. Does not perform any
    cryptographic verification — that is a future production gate.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        identity_tenant_id: str = "staging",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._identity_tenant_id = identity_tenant_id

    async def request_handoff(self, request: BackendHandoffRequest) -> BackendHandoffResult:
        """Call POST /auth/handoff and return a typed outcome.

        Pre-validates empty claim and unsupported client_type before making
        the HTTP call to avoid unnecessary backend round-trips.
        """
        if request.client_type not in SUPPORTED_CLIENT_TYPES:
            return BackendHandoffResult(
                outcome="rejected",
                detail=f"unsupported client_type: {request.client_type!r}",
            )
        if not request.client_identity_claim.strip():
            return BackendHandoffResult(
                outcome="rejected",
                detail="client_identity_claim must not be empty",
            )
        if not request.tenant_id.strip() or not request.user_id.strip():
            return BackendHandoffResult(
                outcome="rejected",
                detail="tenant_id and user_id must not be empty",
            )

        payload = {
            "client_type": request.client_type,
            "client_identity_claim": request.client_identity_claim,
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "ttl_seconds": request.ttl_seconds,
        }

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            ) as http_client:
                resp = await http_client.post("/auth/handoff", json=payload)
        except Exception as exc:
            log.error(
                "crusaderbot_backend_handoff_http_error",
                client_type=request.client_type,
                error=str(exc),
            )
            return BackendHandoffResult(
                outcome="error",
                detail=f"backend call failed: {exc}",
            )

        if resp.status_code == 200:
            try:
                data = resp.json()
                session_id = data.get("session", {}).get("session_id", "")
            except Exception:
                session_id = ""
            log.info(
                "crusaderbot_backend_handoff_issued",
                client_type=request.client_type,
                session_id=session_id,
            )
            return BackendHandoffResult(outcome="issued", session_id=session_id)

        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text or f"http {resp.status_code}"

        log.warning(
            "crusaderbot_backend_handoff_rejected",
            client_type=request.client_type,
            status_code=resp.status_code,
            detail=detail,
        )
        return BackendHandoffResult(
            outcome="rejected" if resp.status_code < 500 else "error",
            detail=detail,
        )

    async def resolve_telegram_identity(
        self, telegram_user_id: str
    ) -> TelegramIdentityResolution:
        """Call GET /auth/telegram-identity/{telegram_user_id} and return typed outcome.

        Passes identity_tenant_id as query param. Returns resolved/not_found/error.
        HTTP failures or unexpected responses return outcome='error'.
        """
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramIdentityResolution(outcome="error")

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            ) as http_client:
                resp = await http_client.get(
                    f"/auth/telegram-identity/{telegram_user_id}",
                    params={"tenant_id": self._identity_tenant_id},
                )
        except Exception as exc:
            log.error(
                "crusaderbot_backend_identity_resolve_http_error",
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramIdentityResolution(outcome="error")

        if resp.status_code == 200:
            try:
                data = resp.json()
                outcome: TelegramIdentityOutcome = data.get("outcome", "error")
                tenant_id: str | None = data.get("tenant_id")
                user_id: str | None = data.get("user_id")
            except Exception:
                return TelegramIdentityResolution(outcome="error")
            return TelegramIdentityResolution(
                outcome=outcome,
                tenant_id=tenant_id,
                user_id=user_id,
            )

        log.warning(
            "crusaderbot_backend_identity_resolve_failed",
            telegram_user_id=telegram_user_id,
            status_code=resp.status_code,
        )
        return TelegramIdentityResolution(outcome="error")

    async def start_telegram_onboarding(
        self, telegram_user_id: str
    ) -> TelegramOnboardingResult:
        """Call POST /auth/telegram-onboarding/start for unresolved users."""
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramOnboardingResult(
                outcome="rejected",
                detail="telegram_user_id must not be empty",
            )

        payload = {
            "telegram_user_id": telegram_user_id,
            "tenant_id": self._identity_tenant_id,
        }

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            ) as http_client:
                resp = await http_client.post("/auth/telegram-onboarding/start", json=payload)
        except Exception as exc:
            log.error(
                "crusaderbot_backend_onboarding_http_error",
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramOnboardingResult(outcome="error", detail=str(exc))

        if resp.status_code == 200:
            try:
                data = resp.json()
                outcome: TelegramOnboardingOutcome = data.get("outcome", "error")
                return TelegramOnboardingResult(
                    outcome=outcome,
                    tenant_id=data.get("tenant_id"),
                    user_id=data.get("user_id"),
                    detail=str(data.get("detail") or ""),
                )
            except Exception:
                return TelegramOnboardingResult(outcome="error", detail="invalid onboarding response")

        detail = ""
        try:
            detail = str(resp.json().get("detail", ""))
        except Exception:
            detail = resp.text or f"http {resp.status_code}"
        return TelegramOnboardingResult(
            outcome="error" if resp.status_code >= 500 else "rejected",
            detail=detail,
        )

    async def confirm_telegram_activation(
        self, telegram_user_id: str
    ) -> TelegramActivationResult:
        """Call POST /auth/telegram-onboarding/confirm for activation confirmation."""
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramActivationResult(
                outcome="rejected",
                detail="telegram_user_id must not be empty",
            )

        payload = {
            "telegram_user_id": telegram_user_id,
            "tenant_id": self._identity_tenant_id,
        }

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            ) as http_client:
                resp = await http_client.post("/auth/telegram-onboarding/confirm", json=payload)
        except Exception as exc:
            log.error(
                "crusaderbot_backend_activation_http_error",
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramActivationResult(outcome="error", detail=str(exc))

        if resp.status_code == 200:
            try:
                data = resp.json()
                outcome: TelegramActivationOutcome = data.get("outcome", "error")
                return TelegramActivationResult(
                    outcome=outcome,
                    tenant_id=data.get("tenant_id"),
                    user_id=data.get("user_id"),
                    detail=str(data.get("detail") or ""),
                )
            except Exception:
                return TelegramActivationResult(outcome="error", detail="invalid activation response")

        detail = ""
        try:
            detail = str(resp.json().get("detail", ""))
        except Exception:
            detail = resp.text or f"http {resp.status_code}"
        return TelegramActivationResult(
            outcome="error" if resp.status_code >= 500 else "rejected",
            detail=detail,
        )

    async def issue_telegram_session(
        self,
        telegram_user_id: str,
        ttl_seconds: int = 1800,
    ) -> TelegramSessionIssuanceResult:
        """Call POST /auth/telegram-onboarding/session-issue for session handoff."""
        if not telegram_user_id or not telegram_user_id.strip():
            return TelegramSessionIssuanceResult(
                outcome="rejected",
                detail="telegram_user_id must not be empty",
            )

        payload = {
            "telegram_user_id": telegram_user_id,
            "tenant_id": self._identity_tenant_id,
            "ttl_seconds": ttl_seconds,
        }

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            ) as http_client:
                resp = await http_client.post("/auth/telegram-onboarding/session-issue", json=payload)
        except Exception as exc:
            log.error(
                "crusaderbot_backend_session_issuance_http_error",
                telegram_user_id=telegram_user_id,
                error=str(exc),
            )
            return TelegramSessionIssuanceResult(outcome="error", detail=str(exc))

        if resp.status_code == 200:
            try:
                data = resp.json()
                outcome: TelegramSessionIssuanceOutcome = data.get("outcome", "error")
                return TelegramSessionIssuanceResult(
                    outcome=outcome,
                    tenant_id=data.get("tenant_id"),
                    user_id=data.get("user_id"),
                    session_id=str(data.get("session_id") or ""),
                    detail=str(data.get("detail") or ""),
                )
            except Exception:
                return TelegramSessionIssuanceResult(
                    outcome="error",
                    detail="invalid session issuance response",
                )

        detail = ""
        try:
            detail = str(resp.json().get("detail", ""))
        except Exception:
            detail = resp.text or f"http {resp.status_code}"
        return TelegramSessionIssuanceResult(
            outcome="error" if resp.status_code >= 500 else "rejected",
            detail=detail,
        )
