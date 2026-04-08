"""Phase 10.6 — CommandRouter: Telegram webhook command dispatcher.

Parses raw Telegram update payloads (JSON dicts) and routes them to
CommandHandler.  Supports both traditional /command args format and the
structured JSON interface defined in Phase 10.6.

Structured command interface::

    {
        "command": "set_risk",
        "value": 0.5
    }

    {
        "command": "status"
    }

Telegram message format::

    /set_risk 0.5
    /status
    /kill

Design:
    - Authorisation: command restricted to allowed user IDs (or unrestricted
      when allowed_user_ids is empty).
    - Idempotent: duplicate update_ids are silently ignored.
    - Structured logging on every routed command.
    - Never raises to caller — returns error CommandResult on any failure.

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import structlog

from .command_handler import CommandHandler, CommandResult

log = structlog.get_logger()


class CommandRouter:
    """Routes incoming Telegram updates to CommandHandler.

    Supports:
        1. Raw Telegram update dicts ({"update_id": ..., "message": {...}}).
        2. Structured command dicts ({"command": "...", "value": ...}).

    Args:
        handler: CommandHandler to dispatch to.
        allowed_user_ids: Set of Telegram user IDs allowed to issue commands.
                          Empty set means unrestricted (all users allowed).
    """

    def __init__(
        self,
        handler: CommandHandler,
        allowed_user_ids: Optional[set[int]] = None,
    ) -> None:
        self._handler = handler
        self._allowed_user_ids: set[int] = allowed_user_ids or set()
        self._seen_update_ids: set[int] = set()
        self._lock = asyncio.Lock()

        log.info(
            "command_router_initialized",
            restricted=bool(allowed_user_ids),
            allowed_count=len(self._allowed_user_ids),
        )

    # ── Primary API ────────────────────────────────────────────────────────────

    async def route_update(self, update: dict) -> Optional[CommandResult]:
        """Route a Telegram update dict to the command handler.

        Supports both Telegram Bot API update format and the simplified
        structured command format ({"command": "...", "value": ...}).

        Args:
            update: Raw Telegram update dict OR structured command dict.

        Returns:
            CommandResult if a command was dispatched, None otherwise.
        """
        # Structured command interface (non-Telegram format)
        if "command" in update and "update_id" not in update:
            return await self._route_structured(update)

        # Telegram update format
        return await self._route_telegram_update(update)

    async def route_structured(self, payload: dict) -> CommandResult:
        """Route a structured command dict.

        Args:
            payload: Dict with "command" key and optional "value", "user_id".

        Returns:
            CommandResult with result of the command.
        """
        return await self._route_structured(payload)

    # ── Internal routing ───────────────────────────────────────────────────────

    async def _route_structured(self, payload: dict) -> CommandResult:
        """Handle a structured {"command": ..., "value": ...} dict."""
        command = str(payload.get("command", "")).strip()
        raw_value = payload.get("value")
        value = raw_value
        user_id = str(payload.get("user_id", "structured"))

        if not command:
            return CommandResult(
                success=False,
                message="❌ Missing 'command' field in structured payload.",
            )

        if raw_value is not None:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                return CommandResult(
                    success=False,
                    message=f"❌ Invalid 'value': expected numeric, got {value!r}",
                )

        return await self._handler.handle(
            command=command,
            value=value,
            user_id=user_id,
            args_text=arg_str if arg_str else None,
        )

    async def _route_telegram_update(self, update: dict) -> Optional[CommandResult]:
        """Handle a Telegram Bot API update dict."""
        update_id = update.get("update_id")

        # Dedup by update_id
        if update_id is not None:
            async with self._lock:
                if update_id in self._seen_update_ids:
                    log.debug("command_router_duplicate_update_id", update_id=update_id)
                    return None
                self._seen_update_ids.add(update_id)
                # Prevent unbounded growth — keep only the last 10 000 IDs
                if len(self._seen_update_ids) > 10_000:
                    self._seen_update_ids = set(
                        sorted(self._seen_update_ids)[-5_000:]
                    )

        message = update.get("message", {})
        if not message:
            return None

        user = message.get("from", {})
        user_id_int: Optional[int] = user.get("id")
        user_id = str(user_id_int) if user_id_int else "unknown"

        # Authorisation check
        if self._allowed_user_ids and user_id_int not in self._allowed_user_ids:
            log.warning(
                "command_router_unauthorised",
                user_id=user_id,
                update_id=update_id,
            )
            return CommandResult(
                success=False,
                message="🚫 Unauthorised. Your user ID is not in the allowed list.",
            )

        text: str = message.get("text", "").strip()
        if not text.startswith("/"):
            return None  # Not a command

        parts = text.split(None, 1)
        raw_cmd = parts[0].split("@")[0]   # strip @botname suffix (e.g. /help@Bot → /help)
        arg_str = parts[1].strip() if len(parts) > 1 else ""

        value: Optional[float] = None
        if arg_str:
            try:
                value = float(arg_str)
            except ValueError:
                pass  # value stays None — handler may use raw args_text

        log.info(
            "command_router_dispatching",
            command=raw_cmd,
            value=value,
            user_id=user_id,
            update_id=update_id,
            timestamp=time.time(),
        )

        return await self._handler.handle(
            command=raw_cmd,
            value=value,
            user_id=user_id,
            args_text=arg_str if arg_str else None,
        )
