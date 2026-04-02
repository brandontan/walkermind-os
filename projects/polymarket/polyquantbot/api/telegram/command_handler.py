"""CommandHandler (api/telegram) — multi-user aware command dispatcher.

Wraps the existing core CommandHandler (telegram/command_handler.py) and
adds per-user context injection.  All commands are scoped by UserContext.

Responsibilities:
    - Accept per-user UserContext on every call.
    - Resolve text commands (/status, /pause …) → core handler.
    - Apply ALLOWED_USER_IDS gate before dispatching.
    - Return CommandResult with inline keyboard when applicable.
    - Send response via Telegram with retry (max 3, exponential backoff).

Delegation rule:
    This class delegates ALL business logic to the existing CommandHandler
    in telegram/command_handler.py.  No trading logic lives here.

Usage::

    handler = TelegramCommandHandler(
        core_handler=existing_command_handler,
        user_manager=user_mgr,
        sender=telegram_send_fn,
        allowed_user_ids={123456789},
    )
    result = await handler.dispatch(
        command="status",
        user_context=ctx,
        chat_id=123,
    )
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import structlog

from ...core.user_context import UserContext
from .user_manager import UserManager

log = structlog.get_logger()

_SEND_TIMEOUT_S: float = 3.0
_MAX_RETRIES: int = 3
_RETRY_BASE_S: float = 0.5


class TelegramCommandHandler:
    """Multi-user Telegram command dispatcher.

    Args:
        core_handler: Existing CommandHandler instance.
        user_manager: UserManager for user auto-creation.
        sender: Async callable(chat_id, text, reply_markup?) for Telegram sends.
        allowed_user_ids: Whitelist of Telegram user IDs.
                          Empty set = all users allowed (env-driven).
    """

    def __init__(
        self,
        core_handler: object,
        user_manager: UserManager,
        sender: object,
        allowed_user_ids: Optional[set[int]] = None,
    ) -> None:
        self._core = core_handler
        self._user_mgr = user_manager
        self._sender = sender
        self._allowed: set[int] = allowed_user_ids or self._load_allowed_from_env()

        log.info(
            "telegram_command_handler_initialized",
            restricted=bool(self._allowed),
            allowed_count=len(self._allowed),
        )

    # ── Primary API ────────────────────────────────────────────────────────────

    async def dispatch(
        self,
        command: str,
        telegram_user_id: int,
        chat_id: int,
        value: Optional[float] = None,
    ) -> None:
        """Dispatch a text command for a specific Telegram user.

        Resolves user context, checks authorisation, delegates to core handler,
        and sends the response back via Telegram.

        Args:
            command: Command string (e.g. "status", "/pause").
            telegram_user_id: Telegram user integer ID.
            chat_id: Chat to send response to.
            value: Optional numeric argument.
        """
        ts = time.time()

        # ── Authorization ─────────────────────────────────────────────────────
        if not self._is_authorized(telegram_user_id):
            log.warning(
                "telegram_cmd_unauthorized",
                telegram_user_id=telegram_user_id,
                command=command,
            )
            await self._send(chat_id, "🚫 Access denied.", None)
            return

        # ── User auto-create ──────────────────────────────────────────────────
        user = await self._user_mgr.get_or_create_user(telegram_user_id)
        ctx = UserContext(
            telegram_user_id=telegram_user_id,
            wallet_id=user.wallet_id,
            request_ts=ts,
        )

        log.info(
            "telegram_cmd_dispatch",
            command=command,
            telegram_user_id=telegram_user_id,
            wallet_id=ctx.wallet_id,
        )

        # ── Delegate to core handler ──────────────────────────────────────────
        try:
            result = await self._core.handle(  # type: ignore[union-attr]
                command=command,
                value=value,
                user_id=str(telegram_user_id),
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "telegram_cmd_core_error",
                command=command,
                telegram_user_id=telegram_user_id,
                error=str(exc),
                exc_info=True,
            )
            await self._send(chat_id, f"⚠️ Error processing `/{command}`.", None)
            return

        if result is None:
            return

        # ── Extract inline keyboard if present ────────────────────────────────
        reply_markup: Optional[list] = None
        if result.payload and "_keyboard" in result.payload:
            reply_markup = result.payload["_keyboard"]

        await self._send(chat_id, result.message, reply_markup)

    # ── Telegram send with retry ───────────────────────────────────────────────

    async def _send(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[list],
    ) -> None:
        """Send message via Telegram with retry (max 3, exponential backoff).

        Never raises — logs error on final failure.

        Args:
            chat_id: Target chat ID.
            text: Message text.
            reply_markup: Optional inline keyboard rows.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                await asyncio.wait_for(
                    self._do_send(chat_id, text, reply_markup),
                    timeout=_SEND_TIMEOUT_S,
                )
                return
            except asyncio.TimeoutError:
                log.warning("telegram_send_timeout", attempt=attempt, chat_id=chat_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "telegram_send_error",
                    attempt=attempt,
                    chat_id=chat_id,
                    error=str(exc),
                )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))

        log.error("telegram_send_all_retries_failed", chat_id=chat_id)

    async def _do_send(
        self, chat_id: int, text: str, reply_markup: Optional[list]
    ) -> None:
        """Invoke the underlying sender callable."""
        if reply_markup is not None:
            await self._sender(chat_id, text, reply_markup)  # type: ignore[operator]
        else:
            await self._sender(chat_id, text)  # type: ignore[operator]

    # ── Auth helpers ───────────────────────────────────────────────────────────

    def _is_authorized(self, telegram_user_id: int) -> bool:
        if not self._allowed:
            return True  # unrestricted
        return telegram_user_id in self._allowed

    @staticmethod
    def _load_allowed_from_env() -> set[int]:
        """Parse ALLOWED_USER_IDS env var (comma-separated ints)."""
        raw = os.getenv("ALLOWED_USER_IDS", "").strip()
        if not raw:
            return set()
        result: set[int] = set()
        for token in raw.split(","):
            token = token.strip()
            if token.isdigit():
                result.add(int(token))
        return result
