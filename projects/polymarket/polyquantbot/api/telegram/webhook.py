"""Telegram webhook handler — routes updates to command or menu layer.

Receives Telegram Bot API updates (POST /telegram/webhook) and routes:
    - message       → TelegramCommandHandler (text commands)
    - callback_query → MenuRouter (inline keyboard callbacks)

Rules:
    - One message per context: uses editMessageText for callbacks (no spam).
    - User auto-created on every first interaction.
    - ALLOWED_USER_IDS enforced at command-handler level.
    - All errors handled — never raises to caller.
    - Structured logging on every update.
    - Deduplication by update_id (rolling 10 000 window).

Usage::

    handler = WebhookHandler(
        command_handler=tg_cmd_handler,
        menu_router=menu_rtr,
        user_manager=user_mgr,
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
    )
    # In aiohttp app:
    app.router.add_post("/telegram/webhook", handler.handle)
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

import structlog

from ...core.user_context import UserContext
from .command_handler import TelegramCommandHandler
from .menu_router import MenuRouter
from .user_manager import UserManager

log = structlog.get_logger()

_MAX_BODY_BYTES: int = 1_048_576  # 1 MB
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_SEND_TIMEOUT_S: float = 5.0
_MAX_RETRIES: int = 3


class WebhookHandler:
    """Routes Telegram updates to command or menu handler.

    Args:
        command_handler: TelegramCommandHandler for text commands.
        menu_router: MenuRouter for inline keyboard callbacks.
        user_manager: UserManager for user resolution.
        bot_token: Telegram Bot API token for sending/editing messages.
        secret_token: Optional webhook secret for request validation.
    """

    def __init__(
        self,
        command_handler: TelegramCommandHandler,
        menu_router: MenuRouter,
        user_manager: UserManager,
        bot_token: str,
        secret_token: Optional[str] = None,
    ) -> None:
        self._cmd = command_handler
        self._menu = menu_router
        self._user_mgr = user_manager
        self._token = bot_token
        self._secret = secret_token

        self._seen_ids: set[int] = set()
        self._dedup_lock = asyncio.Lock()

        log.info(
            "webhook_handler_initialized",
            secret_set=bool(secret_token),
        )

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_env(
        cls,
        command_handler: TelegramCommandHandler,
        menu_router: MenuRouter,
        user_manager: UserManager,
    ) -> "WebhookHandler":
        """Build from environment variables.

        Reads:
            TELEGRAM_BOT_TOKEN
            TELEGRAM_WEBHOOK_SECRET (optional)
        """
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET") or None
        return cls(
            command_handler=command_handler,
            menu_router=menu_router,
            user_manager=user_manager,
            bot_token=token,
            secret_token=secret,
        )

    # ── aiohttp request handler ────────────────────────────────────────────────

    async def handle(self, request: object) -> object:
        """Handle POST /telegram/webhook.

        Returns aiohttp Response (always 200 to prevent Telegram retries).
        """
        from aiohttp import web

        # ── Secret validation ─────────────────────────────────────────────────
        if self._secret:
            provided = getattr(request, "headers", {}).get(  # type: ignore[union-attr]
                "X-Telegram-Bot-Api-Secret-Token", ""
            )
            if provided != self._secret:
                log.warning("webhook_invalid_secret")
                return web.Response(status=403, text="forbidden")

        # ── Parse body ────────────────────────────────────────────────────────
        try:
            body = await request.read()  # type: ignore[union-attr]
            update = json.loads(body.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("webhook_parse_error", error=str(exc))
            return web.Response(status=400, text="bad_request")

        if not isinstance(update, dict):
            return web.Response(status=400, text="expected_dict")

        # ── Deduplication ─────────────────────────────────────────────────────
        update_id = update.get("update_id")
        if update_id is not None:
            async with self._dedup_lock:
                if update_id in self._seen_ids:
                    log.debug("webhook_duplicate_update", update_id=update_id)
                    return web.Response(text="ok")
                self._seen_ids.add(int(update_id))
                if len(self._seen_ids) > 10_000:
                    self._seen_ids = set(sorted(self._seen_ids)[-5_000:])

        # ── Route ─────────────────────────────────────────────────────────────
        asyncio.create_task(self._route(update))
        return web.Response(text="ok")

    # ── Routing ───────────────────────────────────────────────────────────────

    async def _route(self, update: dict) -> None:
        """Route update based on its type (message or callback_query)."""
        try:
            if "message" in update:
                await self._handle_message(update["message"])
            elif "callback_query" in update:
                await self._handle_callback(update["callback_query"])
            else:
                log.debug("webhook_unsupported_update_type", keys=list(update.keys()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("webhook_route_error", error=str(exc), exc_info=True)

    async def _handle_message(self, message: dict) -> None:
        """Route a Telegram message to TelegramCommandHandler."""
        text: str = message.get("text", "").strip()
        if not text.startswith("/"):
            return  # ignore non-commands

        chat_id: int = message.get("chat", {}).get("id", 0)
        user: dict = message.get("from", {})
        telegram_user_id: int = user.get("id", 0)

        if not telegram_user_id or not chat_id:
            log.warning("webhook_message_missing_ids")
            return

        parts = text.split(None, 1)
        raw_cmd = parts[0].split("@")[0].lstrip("/")
        arg_str = parts[1].strip() if len(parts) > 1 else ""

        value: Optional[float] = None
        if arg_str:
            try:
                value = float(arg_str)
            except ValueError:
                pass

        log.info(
            "webhook_message_routing",
            command=raw_cmd,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
        )

        await self._cmd.dispatch(
            command=raw_cmd,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            value=value,
        )

    async def _handle_callback(self, callback_query: dict) -> None:
        """Route a Telegram callback_query to MenuRouter."""
        callback_id: str = callback_query.get("id", "")
        data: str = callback_query.get("data", "").strip()
        user: dict = callback_query.get("from", {})
        telegram_user_id: int = user.get("id", 0)
        message: dict = callback_query.get("message", {})
        chat_id: int = message.get("chat", {}).get("id", 0)
        message_id: int = message.get("message_id", 0)

        if not telegram_user_id or not chat_id or not message_id:
            log.warning("webhook_callback_missing_ids")
            return

        # Answer the callback immediately to remove loading spinner
        asyncio.create_task(self._answer_callback(callback_id))

        # Resolve user context (auto-creates if needed)
        user_record = await self._user_mgr.get_or_create_user(telegram_user_id)
        ctx = UserContext(
            telegram_user_id=telegram_user_id,
            wallet_id=user_record.wallet_id,
        )

        log.info(
            "webhook_callback_routing",
            callback_data=data,
            telegram_user_id=telegram_user_id,
            message_id=message_id,
        )

        await self._menu.route(
            callback_data=data,
            user_context=ctx,
            chat_id=chat_id,
            message_id=message_id,
        )

    # ── Telegram API helpers ───────────────────────────────────────────────────

    async def _answer_callback(self, callback_query_id: str) -> None:
        """Answer a callback query to clear the loading spinner."""
        if not self._token or not callback_query_id:
            return
        url = _TELEGRAM_API_BASE.format(token=self._token, method="answerCallbackQuery")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                await asyncio.wait_for(
                    session.post(url, json={"callback_query_id": callback_query_id}),
                    timeout=3.0,
                )
        except Exception as exc:  # noqa: BLE001
            log.debug("webhook_answer_callback_error", error=str(exc))

    # ── Public edit/send helpers (passed to MenuRouter) ───────────────────────

    async def edit_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: list,
        message_id: int,
    ) -> None:
        """Edit an existing message (inline keyboard update, no spam).

        Retries up to 3× on transient failure.

        Args:
            chat_id: Telegram chat ID.
            text: New message text (Markdown).
            reply_markup: Inline keyboard rows.
            message_id: ID of message to edit.
        """
        if not self._token:
            log.warning("webhook_edit_no_token")
            return

        url = _TELEGRAM_API_BASE.format(token=self._token, method="editMessageText")
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": reply_markup},
        }

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with asyncio.wait_for(
                        session.post(url, json=payload),
                        timeout=_SEND_TIMEOUT_S,
                    ) as resp:
                        if resp.status == 400:
                            body = await resp.text()
                            # Message not modified = benign, skip
                            if "message is not modified" in body.lower():
                                return
                        log.info(
                            "webhook_edit_sent",
                            chat_id=chat_id,
                            message_id=message_id,
                            status=resp.status,
                            attempt=attempt,
                        )
                        return
            except asyncio.TimeoutError:
                log.warning("webhook_edit_timeout", attempt=attempt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("webhook_edit_error", attempt=attempt, error=str(exc))
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        log.error("webhook_edit_all_retries_failed", chat_id=chat_id, message_id=message_id)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[list] = None,
    ) -> None:
        """Send a new message (used for command responses).

        Retries up to 3× on transient failure.
        """
        if not self._token:
            return

        url = _TELEGRAM_API_BASE.format(token=self._token, method="sendMessage")
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_markup is not None:
            payload["reply_markup"] = {"inline_keyboard": reply_markup}

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with asyncio.wait_for(
                        session.post(url, json=payload),
                        timeout=_SEND_TIMEOUT_S,
                    ) as resp:
                        log.info(
                            "webhook_send_sent",
                            chat_id=chat_id,
                            status=resp.status,
                            attempt=attempt,
                        )
                        return
            except asyncio.TimeoutError:
                log.warning("webhook_send_timeout", attempt=attempt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("webhook_send_error", attempt=attempt, error=str(exc))
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        log.error("webhook_send_all_retries_failed", chat_id=chat_id)
