"""Telegram command dispatch boundary for public paper beta control shell."""
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

DispatchOutcome = Literal["session_issued", "rejected", "error", "unknown_command", "ok"]


@dataclass(frozen=True)
class TelegramCommandContext:
    command: str
    from_user_id: str
    chat_id: str
    tenant_id: str
    user_id: str
    argument: str = ""
    ttl_seconds: int = 1800


@dataclass(frozen=True)
class DispatchResult:
    outcome: DispatchOutcome
    reply_text: str
    session_id: str = ""


class TelegramDispatcher:
    def __init__(self, backend: CrusaderBackendClient) -> None:
        self._backend = backend

    async def dispatch(self, ctx: TelegramCommandContext) -> DispatchResult:
        command = ctx.command.strip().lower()
        arg = ctx.argument.strip()
        if command == "/start":
            return await self._dispatch_start(ctx)
        if command == "/mode":
            mode = arg.lower()
            data = await self._backend.beta_post("/beta/mode", {"mode": mode})
            return DispatchResult(outcome="ok", reply_text=f"Mode: {data.get('mode', 'unknown')}")
        if command == "/autotrade":
            enabled = arg.lower() == "on"
            data = await self._backend.beta_post("/beta/autotrade", {"enabled": enabled})
            return DispatchResult(outcome="ok", reply_text=f"Autotrade: {data.get('autotrade', False)}")
        if command == "/positions":
            data = await self._backend.beta_get("/beta/positions")
            return DispatchResult(outcome="ok", reply_text=str(data.get("items", [])))
        if command == "/pnl":
            data = await self._backend.beta_get("/beta/pnl")
            return DispatchResult(outcome="ok", reply_text=f"PnL: {data.get('pnl', 0.0)}")
        if command == "/risk":
            data = await self._backend.beta_get("/beta/risk")
            return DispatchResult(outcome="ok", reply_text=str(data))
        if command == "/status":
            data = await self._backend.beta_get("/beta/status")
            return DispatchResult(outcome="ok", reply_text=str(data))
        if command == "/markets":
            data = await self._backend.beta_get("/beta/markets", params={"query": arg})
            return DispatchResult(outcome="ok", reply_text=str(data.get("items", [])))
        if command == "/market360":
            data = await self._backend.beta_get(f"/beta/market360/{arg}")
            return DispatchResult(outcome="ok", reply_text=str(data))
        if command == "/social":
            data = await self._backend.beta_get("/beta/social", params={"topic": arg or "macro"})
            return DispatchResult(outcome="ok", reply_text=str(data))
        if command == "/kill":
            await self._backend.beta_post("/beta/kill", {})
            return DispatchResult(outcome="ok", reply_text="Kill switch enabled.")

        log.warning("crusaderbot_telegram_dispatch_unknown_command", command=ctx.command, chat_id=ctx.chat_id)
        return DispatchResult(outcome="unknown_command", reply_text="Unknown command.")

    async def _dispatch_start(self, ctx: TelegramCommandContext) -> DispatchResult:
        handoff_ctx = TelegramHandoffContext(
            telegram_user_id=ctx.from_user_id,
            chat_id=ctx.chat_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            ttl_seconds=ctx.ttl_seconds,
        )
        result: HandleStartResult = await handle_start(context=handoff_ctx, backend=self._backend)
        return DispatchResult(outcome=result.outcome, reply_text=result.reply_text, session_id=result.session_id)
