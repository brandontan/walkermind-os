"""Thin async HTTP client bridging Telegram/Web client runtimes to CrusaderBot backend."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import httpx
import structlog

log = structlog.get_logger(__name__)

SUPPORTED_CLIENT_TYPES: frozenset[str] = frozenset({"telegram", "web"})

HandoffOutcome = Literal["issued", "rejected", "error"]


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


class CrusaderBackendClient:
    """Thin async HTTP client for backend handoff calls from client runtimes.

    Makes POST /auth/handoff against the CrusaderBot FastAPI backend and maps
    the HTTP response to a typed BackendHandoffResult. Does not perform any
    cryptographic verification — that is a future production gate.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

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
