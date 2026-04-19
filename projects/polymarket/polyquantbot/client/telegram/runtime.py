"""Telegram runtime adapter and polling loop — inbound update processing foundation.

Phase 8.10: Introduces TelegramIdentityResolver Protocol and updates
TelegramPollingLoop to resolve inbound Telegram from_user_id to real backend
tenant/user scope before command dispatch. Safe fallback reply behavior defined
for not_found and error resolution outcomes.

Phase 8.9: Introduced the adapter boundary for inbound Telegram updates and
outbound reply sending, context extraction from raw Telegram messages, and a
truthful polling loop that drives /start through TelegramDispatcher.

Staging fallback: if no identity_resolver is provided, the polling loop falls
back to the configurable staging_tenant_id / staging_user_id contract. This
preserves backward compatibility for tests and non-identity-wired environments.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx
import structlog

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    TelegramActivationResult,
    CrusaderBackendClient,
    TelegramIdentityResolution,
    TelegramOnboardingResult,
    TelegramSessionIssuanceResult,
)
from projects.polymarket.polyquantbot.client.telegram.dispatcher import (
    DispatchResult,
    TelegramCommandContext,
    TelegramDispatcher,
)

log = structlog.get_logger(__name__)

_STAGING_TENANT_ID = "staging"
_STAGING_USER_ID = "staging"

_REPLY_NOT_REGISTERED = (
    "You are not registered with CrusaderBot yet. Public beta currently supports control commands only after onboarding."
)
_REPLY_ONBOARDED = (
    "Your onboarding request is ready. Please send /start again to continue."
)
_REPLY_ALREADY_LINKED = (
    "Your account is already linked. Please send /start again."
)
_REPLY_ACTIVATED = (
    "Your account is now activated. Please send /start again to continue."
)
_REPLY_SESSION_ISSUED = "Welcome to CrusaderBot. Your session is ready."
_REPLY_ALREADY_ACTIVE_SESSION_ISSUED = (
    "Welcome back. Your account is already active and your session is ready."
)
_REPLY_ACTIVATION_REJECTED = (
    "Activation was rejected. Please contact the bot administrator."
)
_REPLY_ONBOARDING_REJECTED = (
    "Onboarding could not be started. Please contact the bot administrator."
)
_REPLY_IDENTITY_ERROR = "Unable to verify your identity. Please try again later."


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


class TelegramIdentityResolver(Protocol):
    """Protocol for resolving Telegram user IDs to backend user scope.

    Any object that implements resolve_telegram_identity(telegram_user_id) ->
    TelegramIdentityResolution satisfies this protocol. CrusaderBackendClient
    implements this structurally.
    """

    async def resolve_telegram_identity(
        self, telegram_user_id: str
    ) -> TelegramIdentityResolution:
        """Resolve a Telegram user ID to backend tenant/user scope."""
        ...


class TelegramOnboardingInitiator(Protocol):
    """Protocol for starting onboarding/account-link flow for unresolved users."""

    async def start_telegram_onboarding(
        self, telegram_user_id: str
    ) -> TelegramOnboardingResult:
        """Start onboarding and return typed outcome."""
        ...


class TelegramActivationConfirmer(Protocol):
    """Protocol for confirming activation lifecycle after onboarding exists."""

    async def confirm_telegram_activation(
        self, telegram_user_id: str
    ) -> TelegramActivationResult:
        """Confirm activation and return typed outcome."""
        ...


class TelegramSessionIssuer(Protocol):
    """Protocol for issuing backend sessions for activated Telegram-linked users."""

    async def issue_telegram_session(
        self, telegram_user_id: str, ttl_seconds: int = 1800
    ) -> TelegramSessionIssuanceResult:
        """Issue backend session and return typed outcome."""
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
    tenant_id and user_id are placeholder values — callers should supply resolved
    backend identity or rely on the TelegramPollingLoop identity resolver path.
    """
    text = update.text.strip() if update.text else ""
    if not text.startswith("/"):
        return None
    parts = text.split(None, 1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return TelegramCommandContext(
        command=command,
        from_user_id=update.from_user_id,
        chat_id=update.chat_id,
        tenant_id=tenant_id,
        user_id=user_id,
        argument=argument,
    )


class TelegramPollingLoop:
    """Runtime loop that drives inbound Telegram updates through TelegramDispatcher.

    Phase 8.10: When identity_resolver is provided, resolves inbound from_user_id
    to real backend tenant/user scope before dispatch. Unregistered users receive
    a not-registered reply and command dispatch is skipped. Backend errors receive
    a safe error reply. Staging fallback is used when no resolver is wired.

    Phase 8.9 baseline: processes commands (currently /start) via
    dispatcher.dispatch() and sends reply_text back through the adapter boundary.
    Non-command messages are logged and skipped. Dispatch and send_reply
    exceptions are caught, logged, and result in safe error replies.
    """

    def __init__(
        self,
        adapter: TelegramRuntimeAdapter,
        dispatcher: TelegramDispatcher,
        identity_resolver: Optional[TelegramIdentityResolver] = None,
        onboarding_initiator: Optional[TelegramOnboardingInitiator] = None,
        activation_confirmer: Optional[TelegramActivationConfirmer] = None,
        session_issuer: Optional[TelegramSessionIssuer] = None,
        staging_tenant_id: str = _STAGING_TENANT_ID,
        staging_user_id: str = _STAGING_USER_ID,
    ) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher
        self._identity_resolver = identity_resolver
        self._onboarding_initiator = onboarding_initiator
        self._activation_confirmer = activation_confirmer
        self._session_issuer = session_issuer
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

        if self._identity_resolver is not None:
            try:
                resolution = await self._identity_resolver.resolve_telegram_identity(
                    update.from_user_id
                )
            except Exception as exc:
                log.error(
                    "crusaderbot_telegram_identity_resolver_exception",
                    update_id=update.update_id,
                    from_user_id=update.from_user_id,
                    error=str(exc),
                )
                await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                return

            if resolution.outcome == "not_found":
                log.info(
                    "crusaderbot_telegram_identity_not_registered",
                    update_id=update.update_id,
                    from_user_id=update.from_user_id,
                )
                if self._onboarding_initiator is None:
                    await self._safe_send_reply(update.chat_id, _REPLY_NOT_REGISTERED)
                    return
                try:
                    onboarding = await self._onboarding_initiator.start_telegram_onboarding(
                        update.from_user_id
                    )
                except Exception as exc:
                    log.error(
                        "crusaderbot_telegram_onboarding_exception",
                        update_id=update.update_id,
                        from_user_id=update.from_user_id,
                        error=str(exc),
                    )
                    await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                    return

                if onboarding.outcome == "onboarded":
                    await self._safe_send_reply(update.chat_id, _REPLY_ONBOARDED)
                    return
                if onboarding.outcome == "already_linked":
                    await self._safe_send_reply(update.chat_id, _REPLY_ALREADY_LINKED)
                    return
                if onboarding.outcome == "rejected":
                    await self._safe_send_reply(update.chat_id, _REPLY_ONBOARDING_REJECTED)
                    return
                await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                return

            if resolution.outcome == "error":
                log.error(
                    "crusaderbot_telegram_identity_resolution_error",
                    update_id=update.update_id,
                    from_user_id=update.from_user_id,
                )
                await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                return

            # outcome == "resolved" — validate payload before constructing context
            if not resolution.tenant_id or not resolution.user_id:
                log.error(
                    "crusaderbot_telegram_identity_resolved_incomplete",
                    update_id=update.update_id,
                    from_user_id=update.from_user_id,
                    has_tenant_id=bool(resolution.tenant_id),
                    has_user_id=bool(resolution.user_id),
                )
                await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                return

            if self._activation_confirmer is not None:
                try:
                    activation = await self._activation_confirmer.confirm_telegram_activation(
                        update.from_user_id
                    )
                except Exception as exc:
                    log.error(
                        "crusaderbot_telegram_activation_exception",
                        update_id=update.update_id,
                        from_user_id=update.from_user_id,
                        error=str(exc),
                    )
                    await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                    return

                if activation.outcome == "activated":
                    await self._safe_send_reply(update.chat_id, _REPLY_ACTIVATED)
                    return
                if activation.outcome == "rejected":
                    await self._safe_send_reply(update.chat_id, _REPLY_ACTIVATION_REJECTED)
                    return
                if activation.outcome == "error":
                    await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                    return

            if self._session_issuer is not None:
                try:
                    issuance = await self._session_issuer.issue_telegram_session(
                        update.from_user_id,
                        ttl_seconds=ctx.ttl_seconds,
                    )
                except Exception as exc:
                    log.error(
                        "crusaderbot_telegram_session_issuance_exception",
                        update_id=update.update_id,
                        from_user_id=update.from_user_id,
                        error=str(exc),
                    )
                    await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                    return

                if issuance.outcome == "session_issued":
                    await self._safe_send_reply(update.chat_id, _REPLY_SESSION_ISSUED)
                    return
                if issuance.outcome == "already_active_session_issued":
                    await self._safe_send_reply(
                        update.chat_id, _REPLY_ALREADY_ACTIVE_SESSION_ISSUED
                    )
                    return
                if issuance.outcome == "rejected":
                    await self._safe_send_reply(update.chat_id, _REPLY_ACTIVATION_REJECTED)
                    return
                await self._safe_send_reply(update.chat_id, _REPLY_IDENTITY_ERROR)
                return

            ctx = TelegramCommandContext(
                command=ctx.command,
                from_user_id=ctx.from_user_id,
                chat_id=ctx.chat_id,
                tenant_id=resolution.tenant_id,
                user_id=resolution.user_id,
            )

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
    identity_resolver: Optional[TelegramIdentityResolver] = None,
    onboarding_initiator: Optional[TelegramOnboardingInitiator] = None,
    activation_confirmer: Optional[TelegramActivationConfirmer] = None,
    session_issuer: Optional[TelegramSessionIssuer] = None,
    staging_tenant_id: str = _STAGING_TENANT_ID,
    staging_user_id: str = _STAGING_USER_ID,
) -> None:
    """Top-level async polling function. Runs until cancelled.

    Phase 8.10: accepts identity_resolver to replace staging placeholders with
    real backend user scope. When resolver is None, falls back to staging contract.

    Processes updates in run_once() batches. Sleeps briefly when no updates
    are available to avoid tight looping. On unexpected errors, sleeps 5
    seconds before retry to implement natural backoff.
    """
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=identity_resolver,
        onboarding_initiator=onboarding_initiator,
        activation_confirmer=activation_confirmer,
        session_issuer=session_issuer,
        staging_tenant_id=staging_tenant_id,
        staging_user_id=staging_user_id,
    )
    log.info(
        "crusaderbot_telegram_polling_started",
        phase="8.13",
        registered_commands=["/start","/mode","/autotrade","/positions","/pnl","/risk","/status","/markets","/market360","/social","/kill"],
        identity_resolution="enabled" if identity_resolver is not None else "staging_fallback",
        onboarding="enabled" if onboarding_initiator is not None else "disabled",
        activation="enabled" if activation_confirmer is not None else "disabled",
        session_issuance="enabled" if session_issuer is not None else "disabled",
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
