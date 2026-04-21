"""Thin Telegram auth handler — /start command and session handoff dispatch."""
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

HandleStartOutcome = Literal["session_issued", "rejected", "error"]


@dataclass(frozen=True)
class TelegramHandoffContext:
    """Identity context extracted from a Telegram /start event."""

    telegram_user_id: str
    chat_id: str
    tenant_id: str
    user_id: str
    ttl_seconds: int = 1800


@dataclass(frozen=True)
class HandleStartResult:
    """Result of a /start handoff dispatch."""

    outcome: HandleStartOutcome
    session_id: str = ""
    reply_text: str = ""


async def handle_start(
    context: TelegramHandoffContext,
    backend: CrusaderBackendClient,
) -> HandleStartResult:
    """Handle a Telegram /start command by triggering a backend session handoff.

    Dispatches a client_type='telegram' handoff claim to the backend /auth/handoff
    endpoint. The caller is responsible for sending reply_text back to the Telegram
    chat. No Telegram API calls are made here — this layer is backend-driven only.

    Validation at this layer: non-empty telegram_user_id.
    All user-existence and tenant/scope checks are enforced by the backend.
    """
    if not context.telegram_user_id.strip():
        log.warning(
            "crusaderbot_telegram_start_rejected_empty_user_id",
            chat_id=context.chat_id,
        )
        return HandleStartResult(
            outcome="rejected",
            reply_text=(
                "I couldn't verify your Telegram identity yet. "
                "Please send /start again in a moment."
            ),
        )

    request = BackendHandoffRequest(
        client_type="telegram",
        client_identity_claim=context.telegram_user_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        ttl_seconds=context.ttl_seconds,
    )

    result: BackendHandoffResult = await backend.request_handoff(request)

    if result.outcome == "issued":
        log.info(
            "crusaderbot_telegram_start_session_issued",
            chat_id=context.chat_id,
            telegram_user_id=context.telegram_user_id,
            session_id=result.session_id,
        )
        return HandleStartResult(
            outcome="session_issued",
            session_id=result.session_id,
            reply_text=(
                "✅ Welcome to CrusaderBot public paper beta.\n"
                "Your session is ready. Use /help for commands and /status for runtime info."
            ),
        )

    if result.outcome == "rejected":
        log.warning(
            "crusaderbot_telegram_start_rejected",
            chat_id=context.chat_id,
            detail=result.detail,
        )
        return HandleStartResult(
            outcome="rejected",
            reply_text=(
                "⚠️ Session could not be opened right now.\n"
                f"Reason: {result.detail or 'not available'}\n"
                "Please try /start again shortly."
            ),
        )

    log.error(
        "crusaderbot_telegram_start_error",
        chat_id=context.chat_id,
        detail=result.detail,
    )
    return HandleStartResult(
        outcome="error",
        reply_text=(
            "⚠️ Temporary backend issue while starting your session. "
            "Please try again shortly."
        ),
    )
