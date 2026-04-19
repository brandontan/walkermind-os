"""Telegram command dispatch boundary — routes /start to handle_start()."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from projects.polymarket.polyquantbot.client.telegram.backend_client import CrusaderBackendClient
from projects.polymarket.polyquantbot.client.telegram.handlers.auth import (
    HandleStartResult,
    TelegramHandoffContext,
    handle_start,
)

log = structlog.get_logger(__name__)

DispatchOutcome = Literal["session_issued", "rejected", "error", "unknown_command"]


@dataclass(frozen=True)
class TelegramCommandContext:
    """Inbound command context extracted from a Telegram message."""

    command: str
    from_user_id: str
    chat_id: str
    tenant_id: str
    user_id: str
    ttl_seconds: int = 1800


@dataclass(frozen=True)
class DispatchResult:
    """Result of dispatching a Telegram command."""

    outcome: DispatchOutcome
    reply_text: str
    session_id: str = ""


class TelegramDispatcher:
    """Routes Telegram commands to their registered handler functions.

    Phase 8.8 foundation: only /start is registered. Unknown commands receive
    a safe fallback reply without raising. A real Telegram polling loop calls
    dispatch() for each inbound message and sends reply_text back to the chat.
    """

    def __init__(self, backend: CrusaderBackendClient) -> None:
        self._backend = backend

    async def dispatch(self, ctx: TelegramCommandContext) -> DispatchResult:
        """Dispatch a Telegram command to the appropriate handler.

        Routes /start to handle_start(). All other commands return a safe
        unknown_command result. No Telegram API calls are made here.
        """
        command = ctx.command.strip().lower()

        if command == "/start":
            return await self._dispatch_start(ctx)

        log.warning(
            "crusaderbot_telegram_dispatch_unknown_command",
            command=ctx.command,
            chat_id=ctx.chat_id,
        )
        return DispatchResult(
            outcome="unknown_command",
            reply_text="Unknown command. Use /start to begin.",
        )

    async def _dispatch_start(self, ctx: TelegramCommandContext) -> DispatchResult:
        handoff_ctx = TelegramHandoffContext(
            telegram_user_id=ctx.from_user_id,
            chat_id=ctx.chat_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            ttl_seconds=ctx.ttl_seconds,
        )
        result: HandleStartResult = await handle_start(
            context=handoff_ctx,
            backend=self._backend,
        )
        return DispatchResult(
            outcome=result.outcome,
            reply_text=result.reply_text,
            session_id=result.session_id,
        )
