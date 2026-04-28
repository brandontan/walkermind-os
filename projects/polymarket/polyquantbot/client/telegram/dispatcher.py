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
from projects.polymarket.polyquantbot.client.telegram.presentation import (
    format_help_reply,
    format_status_reply,
    format_unknown_command_reply,
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
    _INTERNAL_COMMANDS = {
        "/mode",
        "/autotrade",
        "/positions",
        "/pnl",
        "/risk",
        "/markets",
        "/market360",
        "/social",
        "/kill",
        # Phase C wallet admin commands
        "/wallets",
        "/wallet_enable",
        "/wallet_disable",
        "/halt",
        "/resume",
        # Gate 1c settlement operator commands
        "/settlement_status",
        "/retry_status",
        "/failed_batches",
        "/settlement_intervene",
    }

    def __init__(self, backend: CrusaderBackendClient, operator_chat_id: str = "") -> None:
        self._backend = backend
        self._operator_chat_id = operator_chat_id.strip()
        self._internal_commands_enabled = bool(self._operator_chat_id)
        if not self._internal_commands_enabled:
            log.info(
                "crusaderbot_telegram_internal_commands_disabled",
                reason="missing_operator_chat_id",
            )

    async def dispatch(self, ctx: TelegramCommandContext) -> DispatchResult:
        command = ctx.command.strip().lower()
        arg = ctx.argument.strip()
        if command in self._INTERNAL_COMMANDS and not self._is_internal_command_allowed(ctx):
            log.warning(
                "crusaderbot_telegram_internal_command_guarded",
                command=command,
                chat_id=ctx.chat_id,
                guard_mode=("chat_id_match" if self._internal_commands_enabled else "disabled"),
            )
            return DispatchResult(
                outcome="unknown_command",
                reply_text=format_unknown_command_reply(),
            )
        if command == "/start":
            return await self._dispatch_start(ctx)
        if command == "/help":
            return DispatchResult(
                outcome="ok",
                reply_text=format_help_reply(),
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
                reply_text=format_status_reply(
                    mode=str(data.get("mode", "unknown")),
                    managed_state=str(managed_beta_state.get("state", "unknown")),
                    release_channel=str(
                        data.get("public_readiness_semantics", {}).get("release_channel", "unknown")
                    ),
                    entry_allowed=bool(execution_guard.get("entry_allowed", False)),
                    guard_reasons=reason_text,
                    last_risk_reason=str(data.get("last_risk_reason", "n/a")),
                    kill_switch=bool(data.get("kill_switch", False)),
                    autotrade=bool(data.get("autotrade", False)),
                    position_count=int(data.get("position_count", 0)),
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
                    "Kill switch enabled\n"
                    "• Autotrade forced OFF\n"
                    "• Execution remains paper-only in this beta lane."
                ),
            )

        # ── Phase C wallet admin commands ─────────────────────────────────────
        if command == "/wallets":
            data = await self._backend.orchestration_get("/admin/orchestration/wallets")
            if data.get("status") != "ok":
                return DispatchResult(outcome="ok", reply_text=f"Wallets: unavailable — {data.get('detail', data.get('reason', 'error'))}")
            state = data.get("cross_wallet_state", {})
            wallets = state.get("wallets", [])
            lines = [
                f"Wallets ({state.get('wallet_count', 0)} total, {state.get('active_count', 0)} active)",
                f"• Exposure: {state.get('total_exposure_pct', 0.0):.1%}  Drawdown: {state.get('max_drawdown_pct', 0.0):.1%}",
                f"• Conflict: {state.get('has_conflict', False)}",
            ]
            for w in wallets:
                enabled_marker = "enabled" if w.get("is_enabled") else "DISABLED"
                lines.append(
                    f"  [{enabled_marker}] {w['wallet_id']} | {w.get('lifecycle_status')} | {w.get('risk_state')}"
                )
            return DispatchResult(outcome="ok", reply_text="\n".join(lines))

        if command == "/wallet_enable":
            wallet_id = arg
            if not wallet_id:
                return DispatchResult(outcome="ok", reply_text="Usage: /wallet_enable <wallet_id>")
            data = await self._backend.orchestration_post(f"/admin/orchestration/wallets/{wallet_id}/enable", {})
            if data.get("status") == "ok":
                return DispatchResult(outcome="ok", reply_text=f"Wallet {wallet_id} enabled.\n• {data.get('reason', '')}")
            return DispatchResult(outcome="ok", reply_text=f"Enable failed: {data.get('detail', data.get('reason', 'error'))}")

        if command == "/wallet_disable":
            parts = arg.split(" ", 1)
            wallet_id = parts[0] if parts else ""
            reason = parts[1] if len(parts) > 1 else ""
            if not wallet_id:
                return DispatchResult(outcome="ok", reply_text="Usage: /wallet_disable <wallet_id> [reason]")
            data = await self._backend.orchestration_post(
                f"/admin/orchestration/wallets/{wallet_id}/disable",
                {"reason": reason},
            )
            if data.get("status") == "ok":
                return DispatchResult(outcome="ok", reply_text=f"Wallet {wallet_id} disabled.\n• {data.get('reason', '')}")
            return DispatchResult(outcome="ok", reply_text=f"Disable failed: {data.get('detail', data.get('reason', 'error'))}")

        if command == "/halt":
            reason = arg or "operator halt via Telegram"
            data = await self._backend.orchestration_post("/admin/orchestration/halt", {"reason": reason})
            if data.get("status") == "ok":
                return DispatchResult(outcome="ok", reply_text=f"Global halt set.\n• Reason: {reason}\n• All routing blocked until /resume.")
            return DispatchResult(outcome="ok", reply_text=f"Halt failed: {data.get('detail', data.get('reason', 'error'))}")

        if command == "/resume":
            data = await self._backend.orchestration_delete("/admin/orchestration/halt")
            if data.get("status") == "ok":
                return DispatchResult(outcome="ok", reply_text="Global halt cleared. Routing resumed.")
            return DispatchResult(outcome="ok", reply_text=f"Resume failed: {data.get('detail', data.get('reason', 'error'))}")

        # ── Gate 1c settlement operator commands ──────────────────────────────
        if command == "/settlement_status":
            workflow_id = arg
            if not workflow_id:
                return DispatchResult(outcome="ok", reply_text="Usage: /settlement_status <workflow_id>")
            data = await self._backend.settlement_get(f"/admin/settlement/status/{workflow_id}")
            if not data.get("ok"):
                return DispatchResult(outcome="ok", reply_text=f"Settlement status: unavailable — {data.get('detail', 'error')}")
            d = data.get("data", {})
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    f"Settlement status: {workflow_id}\n"
                    f"• Status: {d.get('status', 'unknown')}\n"
                    f"• Retry attempts: {d.get('retry_attempt_count', 0)}\n"
                    f"• Amount: {d.get('amount', 0.0)} {d.get('currency', '')}\n"
                    f"• Mode: {d.get('mode', 'unknown')}\n"
                    f"• Blocked reason: {d.get('last_blocked_reason') or 'none'}\n"
                    f"• Wallet: {d.get('wallet_id') or 'n/a'}"
                ),
            )

        if command == "/retry_status":
            workflow_id = arg
            if not workflow_id:
                return DispatchResult(outcome="ok", reply_text="Usage: /retry_status <workflow_id>")
            data = await self._backend.settlement_get(f"/admin/settlement/retry/{workflow_id}")
            if not data.get("ok"):
                return DispatchResult(outcome="ok", reply_text=f"Retry status: unavailable — {data.get('detail', 'error')}")
            d = data.get("data", {})
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    f"Retry status: {workflow_id}\n"
                    f"• Total attempts: {d.get('current_attempt', 0)}\n"
                    f"• Exhausted: {d.get('is_exhausted', False)}\n"
                    f"• Last error: {d.get('last_outcome') or 'none'}\n"
                    f"• Next retry at: {d.get('next_retry_at') or 'n/a'}"
                ),
            )

        if command == "/failed_batches":
            data = await self._backend.settlement_get("/admin/settlement/failed-batches")
            if not data.get("ok"):
                return DispatchResult(outcome="ok", reply_text=f"Failed batches: unavailable — {data.get('detail', 'error')}")
            batches = data.get("data", [])
            if not batches:
                return DispatchResult(
                    outcome="ok",
                    reply_text="Failed batches: none\n• Note: batch result persistence is not yet active; this list will always be empty until that lane is built.",
                )
            lines = [f"Failed batches ({len(batches)})"]
            for b in batches:
                lines.append(f"  • {b.get('batch_id', 'unknown')} | {b.get('batch_status', 'unknown')}")
            return DispatchResult(outcome="ok", reply_text="\n".join(lines))

        if command == "/settlement_intervene":
            parts = arg.split(None, 2)
            if len(parts) < 2:
                return DispatchResult(
                    outcome="ok",
                    reply_text="Usage: /settlement_intervene <workflow_id> <action> [reason]",
                )
            workflow_id, action = parts[0], parts[1]
            reason = parts[2] if len(parts) > 2 else "operator intervention via Telegram"
            payload: dict[str, object] = {
                "workflow_id": workflow_id,
                "action": action,
                "admin_user_id": ctx.from_user_id,
                "reason": reason,
            }
            data = await self._backend.settlement_post("/admin/settlement/intervene", payload)
            if not data.get("ok"):
                detail = data.get("detail", "error")
                if "http_404" in str(detail):
                    return DispatchResult(outcome="ok", reply_text=f"Intervention: workflow {workflow_id} not found.")
                return DispatchResult(outcome="ok", reply_text=f"Intervention failed: {detail}")
            d = data.get("data", {})
            return DispatchResult(
                outcome="ok",
                reply_text=(
                    f"Intervention applied: {workflow_id}\n"
                    f"• Action: {action}\n"
                    f"• Applied: {d.get('success', False)}\n"
                    f"• Resulting status: {d.get('new_status', 'unknown')}\n"
                    f"• Note: intervention record is not persisted in current layer."
                ),
            )

        log.warning("crusaderbot_telegram_dispatch_unknown_command", command=ctx.command, chat_id=ctx.chat_id)
        return DispatchResult(
            outcome="unknown_command",
            reply_text=format_unknown_command_reply(),
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

    def _is_internal_command_allowed(self, ctx: TelegramCommandContext) -> bool:
        if not self._internal_commands_enabled:
            return False
        return ctx.chat_id == self._operator_chat_id
