"""Minimal web handoff surface — client_type='web' session dispatch foundation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    BackendHandoffRequest,
    BackendHandoffResult,
    CrusaderBackendClient,
)

log = structlog.get_logger(__name__)

WebHandoffOutcome = Literal["session_issued", "rejected", "error"]


@dataclass(frozen=True)
class WebHandoffContext:
    """Identity context for a web-originating handoff request."""

    client_identity_claim: str
    tenant_id: str
    user_id: str
    ttl_seconds: int = 1800


@dataclass(frozen=True)
class WebHandoffResult:
    """Result of a web handoff dispatch."""

    outcome: WebHandoffOutcome
    session_id: str = ""
    detail: str = ""


async def handle_web_handoff(
    context: WebHandoffContext,
    backend: CrusaderBackendClient,
) -> WebHandoffResult:
    """Dispatch a web identity claim to the backend /auth/handoff endpoint.

    Validates non-empty client_identity_claim locally. All user-existence and
    tenant/scope checks are enforced by the backend. Returns a typed result
    for the web request handler to map into its HTTP response.

    This is a foundation surface. Full web UX, OAuth, and RBAC are out of scope.
    """
    if not context.client_identity_claim.strip():
        log.warning(
            "crusaderbot_web_handoff_rejected_empty_claim",
            tenant_id=context.tenant_id,
        )
        return WebHandoffResult(
            outcome="rejected",
            detail="client_identity_claim must not be empty",
        )

    request = BackendHandoffRequest(
        client_type="web",
        client_identity_claim=context.client_identity_claim,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        ttl_seconds=context.ttl_seconds,
    )

    result: BackendHandoffResult = await backend.request_handoff(request)

    if result.outcome == "issued":
        log.info(
            "crusaderbot_web_handoff_session_issued",
            tenant_id=context.tenant_id,
            session_id=result.session_id,
        )
        return WebHandoffResult(outcome="session_issued", session_id=result.session_id)

    if result.outcome == "rejected":
        log.warning(
            "crusaderbot_web_handoff_rejected",
            tenant_id=context.tenant_id,
            detail=result.detail,
        )
        return WebHandoffResult(outcome="rejected", detail=result.detail)

    log.error(
        "crusaderbot_web_handoff_error",
        tenant_id=context.tenant_id,
        detail=result.detail,
    )
    return WebHandoffResult(outcome="error", detail=result.detail)
