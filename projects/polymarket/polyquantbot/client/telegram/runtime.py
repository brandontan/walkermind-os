"""Telegram runtime adapter and polling loop — inbound update processing foundation.

Phase 8.9: Introduces the adapter boundary for inbound Telegram updates and
outbound reply sending, context extraction from raw Telegram messages, and a
truthful polling loop that drives /start through TelegramDispatcher.

Staging identity contract: tenant_id and user_id are not derivable from
inbound Telegram updates without a backend user lookup. For Phase 8.9 foundation,
configurable staging values are used. Production identity resolution is a
follow-up lane.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from projects.polymarket.polyquantbot.client.telegram.dispatcher import (
    DispatchResult,
    TelegramCommandContext,
    TelegramDispatcher,
)

log = structlog.get_logger(__name__)

_STAGING_TENANT_ID = "staging"
_STAGING_USER_ID = "staging"


@dataclass(frozen=True)
class TelegramInboundUpdate:
    """Normalized inbound Telegram update carrying message fields."""

    update_id: int
    chat_id: str
    from_user_id: str
    text: str
    message_id: int = 0


class TelegramRuntimeAdapter(ABC):
    """Abstract boundary for inbound Telegram updates and outbound reply sending.

    Concrete implementations call the Telegram Bot API, a mock, or any other
    update source. The polling loop and dispatcher operate only against this
    boundary — never against raw Telegram API details.
    """

    @abstractmethod
    async def get_updates(self, offset: int = 0, limit: int = 100) -> list[TelegramInboundUpdate]:
        """Fetch a batch of inbound updates starting from offset."""
        ...

    @abstractmethod
    async def send_reply(self, chat_id: str, text: str) -> None:
        """Send reply text to a Telegram chat."""
        ...


class HttpTelegramAdapter(TelegramRuntimeAdapter):
    """Concrete Telegram adapter that calls the Telegram Bot API via httpx.

    Uses long-poll timeout (default 30s) on getUpdates to minimize round-trips.
    HTTP errors surface as exceptions — callers handle retry/backoff.
    """

    _API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        token: str,
        long_poll_timeout: int = 30,
        http_timeout: float = 35.0,
    ) -> None:
        if not token.strip():
            raise ValueError("Telegram bot token must not be empty")
        self._token = token.strip()
        self._long_poll_timeout = long_poll_timeout
        self._http_timeout = http_timeout

    def _bot_url(self, method: str) -> str:
        return f"{self._API_BASE}/bot{self._token}/{method}"

    async def get_updates(self, offset: int = 0, limit: int = 100) -> list[TelegramInboundUpdate]:
        """Call getUpdates and return normalized inbound updates.

        Returns only updates that carry a message with a non-empty chat_id
        and from_id. Updates without these fields are silently skipped.
        """
        params: dict[str, int] = {
            "offset": offset,
            "limit": limit,
            "timeout": self._long_poll_timeout,
        }
        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
            resp = await client.get(self._bot_url("getUpdates"), params=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates returned ok=false: {data}")
        results = []
        for raw in data.get("result", []):
            parsed = self._parse_single_update(raw)
            if parsed is not None:
                results.append(parsed)
        return results

    @staticmethod
    def _parse_single_update(raw: dict) -> Optional[TelegramInboundUpdate]:
        """Parse a single raw Telegram update dict into TelegramInboundUpdate.

        Returns None for updates without a message, chat_id, or from_id.
        """
        try:
            update_id = int(raw["update_id"])
            message = raw.get("message") or {}
            chat_id = str(message.get("chat", {}).get("id", ""))
            from_id = str(message.get("from", {}).get("id", ""))
            text = message.get("text", "") or ""
            message_id = int(message.get("message_id", 0))
            if not chat_id or not from_id:
                return None
            return TelegramInboundUpdate(
                update_id=update_id,
                chat_id=chat_id,
                from_user_id=from_id,
                text=text,
                message_id=message_id,
            )
        except (KeyError, ValueError, TypeError):
            return None

    async def send_reply(self, chat_id: str, text: str) -> None:
        """Call sendMessage to deliver reply text to a Telegram chat."""
        payload = {"chat_id": chat_id, "text": text}
        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
            resp = await client.post(self._bot_url("sendMessage"), json=payload)
        resp.raise_for_status()


def extract_command_context(
    update: TelegramInboundUpdate,
    tenant_id: str = _STAGING_TENANT_ID,
    user_id: str = _STAGING_USER_ID,
) -> Optional[TelegramCommandContext]:
    """Extract TelegramCommandContext from an inbound update if it carries a command.

    Returns None for non-command messages (text not starting with '/').
    tenant_id and user_id use the staging contract for Phase 8.9 — production
    identity resolution from Telegram user data is a follow-up lane.
    """
    text = update.text.strip() if update.text else ""
    if not text.startswith("/"):
        return None
    parts = text.split(None, 1)
    command = parts[0].lower()
    return TelegramCommandContext(
        command=command,
        from_user_id=update.from_user_id,
        chat_id=update.chat_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


class TelegramPollingLoop:
    """Runtime loop that drives inbound Telegram updates through TelegramDispatcher.

    Phase 8.9 foundation: processes commands (currently /start) via
    dispatcher.dispatch() and sends reply_text back through the adapter boundary.
    Non-command messages are logged and skipped. Dispatch and send_reply
    exceptions are caught, logged, and result in safe error replies — the loop
    does not crash on individual update failures.
    """

    def __init__(
        self,
        adapter: TelegramRuntimeAdapter,
        dispatcher: TelegramDispatcher,
        staging_tenant_id: str = _STAGING_TENANT_ID,
        staging_user_id: str = _STAGING_USER_ID,
    ) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher
        self._staging_tenant_id = staging_tenant_id
        self._staging_user_id = staging_user_id
        self._offset: int = 0

    async def run_once(self) -> int:
        """Fetch one batch of updates, process each, and advance offset.

        Returns the number of updates processed. Returns 0 when no updates
        were available — callers may add a brief sleep to avoid tight looping.
        """
        updates = await self._adapter.get_updates(offset=self._offset)
        processed = 0
        for update in updates:
            await self._process_update(update)
            self._offset = update.update_id + 1
            processed += 1
        return processed

    async def _process_update(self, update: TelegramInboundUpdate) -> None:
        ctx = extract_command_context(
            update,
            tenant_id=self._staging_tenant_id,
            user_id=self._staging_user_id,
        )
        if ctx is None:
            log.info(
                "crusaderbot_telegram_runtime_skip_non_command",
                update_id=update.update_id,
                chat_id=update.chat_id,
            )
            return

        try:
            result: DispatchResult = await self._dispatcher.dispatch(ctx)
        except Exception as exc:
            log.error(
                "crusaderbot_telegram_runtime_dispatch_error",
                update_id=update.update_id,
                chat_id=update.chat_id,
                error=str(exc),
            )
            await self._safe_send_reply(
                update.chat_id,
                "A runtime error occurred. Please try again.",
            )
            return

        await self._safe_send_reply(update.chat_id, result.reply_text)

    async def _safe_send_reply(self, chat_id: str, text: str) -> None:
        try:
            await self._adapter.send_reply(chat_id, text)
        except Exception as exc:
            log.error(
                "crusaderbot_telegram_runtime_send_reply_error",
                chat_id=chat_id,
                error=str(exc),
            )


async def run_polling_loop(
    adapter: TelegramRuntimeAdapter,
    dispatcher: TelegramDispatcher,
    staging_tenant_id: str = _STAGING_TENANT_ID,
    staging_user_id: str = _STAGING_USER_ID,
) -> None:
    """Top-level async polling function. Runs until cancelled.

    Processes updates in run_once() batches. Sleeps briefly when no updates
    are available to avoid tight looping. On unexpected errors, sleeps 5
    seconds before retry to implement natural backoff.
    """
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        staging_tenant_id=staging_tenant_id,
        staging_user_id=staging_user_id,
    )
    log.info(
        "crusaderbot_telegram_polling_started",
        phase="8.9",
        registered_commands=["/start"],
        staging_tenant_id=staging_tenant_id,
        staging_user_id=staging_user_id,
    )
    while True:
        try:
            count = await loop.run_once()
            if count == 0:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            log.info("crusaderbot_telegram_polling_cancelled")
            return
        except Exception as exc:
            log.error("crusaderbot_telegram_polling_error", error=str(exc))
            await asyncio.sleep(5.0)
