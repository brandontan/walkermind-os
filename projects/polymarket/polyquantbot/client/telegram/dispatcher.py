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
        if command == "/help":
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "📘 CrusaderBot commands (public paper beta)\n"
                    "• /start — initialize or refresh your session\n"
                    "• /help — show command list\n"
                    "• /status — runtime and guard snapshot\n"
                    "Boundary: paper-only execution, no live trading, no production capital."
                ),
            )
        if command == "/mode":
            mode = arg.lower()
            data = await self._backend.beta_post("/beta/mode", {"mode": mode})
            detail = data.get("detail", "")
            mode_updated = bool(data.get("ok", False))
            prefix = "✅ Mode updated" if mode_updated else "⚠️ Mode change blocked"
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    f"{prefix}\n"
                    f"• Current mode: {data.get('mode', 'unknown')}\n"
                    "• Execution boundary: paper-only\n"
                    f"• Guard detail: {detail or 'n/a'}"
                ),
            )
        if command == "/autotrade":
            enabled = arg.lower() == "on"
            data = await self._backend.beta_post("/beta/autotrade", {"enabled": enabled})
            detail = data.get("detail", "")
            status = "ON" if data.get("autotrade", False) else "OFF"
            message = (
                "🤖 Autotrade updated\n"
                f"• Status: {status}\n"
                "• Scope: control-plane toggle for paper execution only"
            )
            if detail:
                message += f"\n• Guard: {detail}"
            return DispatchResult(outcome="ok", reply_text=message)
        if command == "/positions":
            data = await self._backend.beta_get("/beta/positions")
            items = data.get("items", [])
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "📌 Positions (paper beta)\n"
                    f"• Open positions: {len(items)}\n"
                    "• Boundary: read-only surface (no manual order entry commands)\n"
                    f"• Detail: {items}"
                ),
            )
        if command == "/pnl":
            data = await self._backend.beta_get("/beta/pnl")
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "📊 PnL (paper beta)\n"
                    f"• Unrealized + realized: {data.get('pnl', 0.0)}\n"
                    "• Interpretation: informational metric; no live settlement path in this lane"
                ),
            )
        if command == "/risk":
            data = await self._backend.beta_get("/beta/risk")
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "🛡 Risk snapshot\n"
                    f"• Drawdown: {data.get('drawdown', 0.0)}\n"
                    f"• Exposure: {data.get('exposure', 0.0)}\n"
                    f"• Last reason: {data.get('last_reason', 'n/a')}\n"
                    f"• Kill switch: {data.get('kill_switch', False)}\n"
                    f"• Autotrade enabled: {data.get('autotrade_enabled', False)}\n"
                    "• Boundary: risk state governs paper execution only"
                ),
            )
        if command == "/status":
            data = await self._backend.beta_get("/beta/status")
            execution_guard = data.get("execution_guard", {})
            blocked_reasons = execution_guard.get("blocked_reasons", [])
            reason_text = ", ".join(blocked_reasons) if blocked_reasons else "none"
            managed_beta_state = data.get("managed_beta_state", {})
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "🧭 Runtime status (public paper beta)\n"
                    f"• Mode: {data.get('mode', 'unknown')}\n"
                    f"• Autotrade: {data.get('autotrade', False)}\n"
                    f"• Kill switch: {data.get('kill_switch', False)}\n"
                    f"• Position count: {data.get('position_count', 0)}\n"
                    f"• Guard allows entry: {execution_guard.get('entry_allowed', False)}\n"
                    f"• Guard reasons: {reason_text}\n"
                    f"• Last risk reason: {data.get('last_risk_reason', 'n/a')}\n"
                    f"• Managed beta state: {managed_beta_state.get('state', 'unknown')}\n"
                    f"• Release channel: {data.get('public_readiness_semantics', {}).get('release_channel', 'unknown')}\n"
                    "• Boundary: paper-only execution; Telegram is control/read surface"
                ),
            )
        if command == "/markets":
            data = await self._backend.beta_get("/beta/markets", params={"query": arg})
            items = data.get("items", [])
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "🧾 Market scan (Falcon read-side)\n"
                    f"• Query: {arg or '(default)'}\n"
                    f"• Matches: {len(items)}\n"
                    f"• Detail: {items}"
                ),
            )
        if command == "/market360":
            data = await self._backend.beta_get(f"/beta/market360/{arg}")
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "🔎 Market360 (bounded placeholder surface)\n"
                    f"• Condition: {arg or '(missing)'}\n"
                    f"• Detail: {data}"
                ),
            )
        if command == "/social":
            data = await self._backend.beta_get("/beta/social", params={"topic": arg or "macro"})
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "🌐 Social pulse (Falcon read-side)\n"
                    f"• Topic: {arg or 'macro'}\n"
                    f"• Detail: {data}"
                ),
            )
        if command == "/kill":
            await self._backend.beta_post("/beta/kill", {})
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    "🛑 Kill switch enabled\n"
                    "• Autotrade forced OFF\n"
                    "• Execution remains paper-only in this beta lane."
                ),
            )

        log.warning("crusaderbot_telegram_dispatch_unknown_command", command=ctx.command, chat_id=ctx.chat_id)
        return DispatchResult(
            outcome="unknown_command",
            reply_text=(
                "Unknown command for CrusaderBot public paper beta.\n"
                "Supported: /start /help /mode /autotrade /positions /pnl /risk /status /markets /market360 /social /kill\n"
                "Note: no manual trade-entry commands are available in this beta."
            ),
        )

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
