"""Phase 8.10 — Telegram Identity Resolution Foundation tests.

Covers:
- TelegramIdentityService: resolved, not_found, error, empty input paths
- CrusaderBackendClient.resolve_telegram_identity: HTTP resolved, not_found, error
- TelegramPollingLoop with identity resolver:
  - resolved identity -> dispatch with real tenant_id/user_id
  - not_found -> unregistered reply, no dispatch invoked
  - error -> identity error reply, no dispatch invoked
  - resolver exception -> identity error reply, no dispatch invoked
  - no resolver (None) -> staging fallback (backward compat)
  - resolved context carries real tenant_id/user_id in dispatched command
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    CrusaderBackendClient,
    TelegramIdentityResolution,
)
from projects.polymarket.polyquantbot.client.telegram.dispatcher import (
    DispatchResult,
    TelegramCommandContext,
    TelegramDispatcher,
)
from projects.polymarket.polyquantbot.client.telegram.runtime import (
    TelegramInboundUpdate,
    TelegramPollingLoop,
    TelegramRuntimeAdapter,
    _REPLY_IDENTITY_ERROR,
    _REPLY_NOT_REGISTERED,
    extract_command_context,
)
from projects.polymarket.polyquantbot.server.schemas.multi_user import UserRecord, now_utc
from projects.polymarket.polyquantbot.server.services.telegram_identity_service import (
    TelegramIdentityService,
)
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.storage.in_memory_store import InMemoryMultiUserStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: str = "usr_test001",
    tenant_id: str = "t1",
    external_id: str = "tg_12345678",
) -> UserRecord:
    return UserRecord(
        user_id=user_id,
        tenant_id=tenant_id,
        external_id=external_id,
        created_at=now_utc(),
    )


def _make_update(
    update_id: int = 1,
    chat_id: str = "chat_001",
    from_user_id: str = "12345678",
    text: str = "/start",
) -> TelegramInboundUpdate:
    return TelegramInboundUpdate(
        update_id=update_id,
        chat_id=chat_id,
        from_user_id=from_user_id,
        text=text,
    )


class MockTelegramAdapter(TelegramRuntimeAdapter):
    def __init__(self, updates: list[TelegramInboundUpdate]) -> None:
        self._updates = updates
        self.replies: list[tuple[str, str]] = []

    async def get_updates(self, offset: int = 0, limit: int = 100) -> list[TelegramInboundUpdate]:
        return [u for u in self._updates if u.update_id >= offset]

    async def send_reply(self, chat_id: str, text: str) -> None:
        self.replies.append((chat_id, text))


class MockIdentityResolver:
    def __init__(self, resolution: TelegramIdentityResolution) -> None:
        self._resolution = resolution
        self.calls: list[str] = []

    async def resolve_telegram_identity(
        self, telegram_user_id: str
    ) -> TelegramIdentityResolution:
        self.calls.append(telegram_user_id)
        return self._resolution


# ---------------------------------------------------------------------------
# TelegramIdentityService tests
# ---------------------------------------------------------------------------


def test_telegram_identity_service_resolve_success() -> None:
    store = InMemoryMultiUserStore()
    user = _make_user(user_id="usr_abc", tenant_id="t1", external_id="tg_12345678")
    store.put_user(user)
    service = TelegramIdentityService(user_service=UserService(store=store))

    resolution = service.resolve(telegram_user_id="12345678", tenant_id="t1")

    assert resolution.outcome == "resolved"
    assert resolution.tenant_id == "t1"
    assert resolution.user_id == "usr_abc"
    assert resolution.error_detail is None


def test_telegram_identity_service_resolve_not_found() -> None:
    store = InMemoryMultiUserStore()
    service = TelegramIdentityService(user_service=UserService(store=store))

    resolution = service.resolve(telegram_user_id="99999999", tenant_id="t1")

    assert resolution.outcome == "not_found"
    assert resolution.tenant_id is None
    assert resolution.user_id is None


def test_telegram_identity_service_resolve_wrong_tenant() -> None:
    store = InMemoryMultiUserStore()
    user = _make_user(user_id="usr_abc", tenant_id="t1", external_id="tg_12345678")
    store.put_user(user)
    service = TelegramIdentityService(user_service=UserService(store=store))

    resolution = service.resolve(telegram_user_id="12345678", tenant_id="other_tenant")

    assert resolution.outcome == "not_found"


def test_telegram_identity_service_resolve_empty_telegram_user_id() -> None:
    store = InMemoryMultiUserStore()
    service = TelegramIdentityService(user_service=UserService(store=store))

    resolution = service.resolve(telegram_user_id="", tenant_id="t1")

    assert resolution.outcome == "error"
    assert resolution.error_detail is not None


def test_telegram_identity_service_resolve_empty_tenant_id() -> None:
    store = InMemoryMultiUserStore()
    service = TelegramIdentityService(user_service=UserService(store=store))

    resolution = service.resolve(telegram_user_id="12345678", tenant_id="")

    assert resolution.outcome == "error"
    assert resolution.error_detail is not None


def test_telegram_identity_service_resolve_store_exception() -> None:
    store = InMemoryMultiUserStore()
    user_service = UserService(store=store)

    def raise_exc(tenant_id: str, external_id: str) -> None:
        raise RuntimeError("store read failure")

    user_service.get_user_by_external_id = raise_exc  # type: ignore[method-assign]
    service = TelegramIdentityService(user_service=user_service)

    resolution = service.resolve(telegram_user_id="12345678", tenant_id="t1")

    assert resolution.outcome == "error"
    assert "store read failure" in (resolution.error_detail or "")


# ---------------------------------------------------------------------------
# CrusaderBackendClient.resolve_telegram_identity tests
# ---------------------------------------------------------------------------


def test_backend_client_resolve_telegram_identity_resolved() -> None:
    client = CrusaderBackendClient(
        base_url="http://localhost:8080",
        identity_tenant_id="t1",
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "outcome": "resolved",
        "tenant_id": "t1",
        "user_id": "usr_abc",
    }

    async def run() -> TelegramIdentityResolution:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_http
            return await client.resolve_telegram_identity("12345678")

    resolution = asyncio.get_event_loop().run_until_complete(run())

    assert resolution.outcome == "resolved"
    assert resolution.tenant_id == "t1"
    assert resolution.user_id == "usr_abc"


def test_backend_client_resolve_telegram_identity_not_found() -> None:
    client = CrusaderBackendClient(
        base_url="http://localhost:8080",
        identity_tenant_id="t1",
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "outcome": "not_found",
        "tenant_id": None,
        "user_id": None,
    }

    async def run() -> TelegramIdentityResolution:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_http
            return await client.resolve_telegram_identity("99999999")

    resolution = asyncio.get_event_loop().run_until_complete(run())

    assert resolution.outcome == "not_found"
    assert resolution.tenant_id is None
    assert resolution.user_id is None


def test_backend_client_resolve_telegram_identity_http_error() -> None:
    client = CrusaderBackendClient(
        base_url="http://localhost:8080",
        identity_tenant_id="t1",
    )

    async def run() -> TelegramIdentityResolution:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=RuntimeError("connection refused"))
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_http
            return await client.resolve_telegram_identity("12345678")

    resolution = asyncio.get_event_loop().run_until_complete(run())

    assert resolution.outcome == "error"


def test_backend_client_resolve_telegram_identity_empty_id() -> None:
    client = CrusaderBackendClient(base_url="http://localhost:8080")

    async def run() -> TelegramIdentityResolution:
        return await client.resolve_telegram_identity("")

    resolution = asyncio.get_event_loop().run_until_complete(run())

    assert resolution.outcome == "error"


# ---------------------------------------------------------------------------
# TelegramPollingLoop with identity resolver tests
# ---------------------------------------------------------------------------


def _make_dispatcher_with_start_reply(reply: str = "Welcome!") -> TelegramDispatcher:
    backend = MagicMock(spec=CrusaderBackendClient)
    dispatcher = MagicMock(spec=TelegramDispatcher)
    dispatcher.dispatch = AsyncMock(
        return_value=DispatchResult(
            outcome="session_issued",
            reply_text=reply,
            session_id="sess_001",
        )
    )
    return dispatcher


def test_polling_loop_with_resolver_resolved_dispatches_command() -> None:
    update = _make_update(from_user_id="12345678", text="/start")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply("Welcome!")
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="resolved", tenant_id="t1", user_id="usr_abc")
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    dispatcher.dispatch.assert_awaited_once()
    dispatched_ctx: TelegramCommandContext = dispatcher.dispatch.call_args[0][0]
    assert dispatched_ctx.tenant_id == "t1"
    assert dispatched_ctx.user_id == "usr_abc"


def test_polling_loop_with_resolver_resolved_sends_dispatch_reply() -> None:
    update = _make_update(from_user_id="12345678", text="/start", chat_id="chat_A")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply("Welcome!")
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="resolved", tenant_id="t1", user_id="usr_abc")
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert len(adapter.replies) == 1
    assert adapter.replies[0] == ("chat_A", "Welcome!")


def test_polling_loop_with_resolver_not_found_sends_unregistered_reply() -> None:
    update = _make_update(from_user_id="99999999", text="/start", chat_id="chat_B")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply()
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="not_found")
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert len(adapter.replies) == 1
    assert adapter.replies[0][0] == "chat_B"
    assert adapter.replies[0][1] == _REPLY_NOT_REGISTERED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_with_resolver_error_sends_identity_error_reply() -> None:
    update = _make_update(from_user_id="12345678", text="/start", chat_id="chat_C")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply()
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="error")
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert len(adapter.replies) == 1
    assert adapter.replies[0][0] == "chat_C"
    assert adapter.replies[0][1] == _REPLY_IDENTITY_ERROR
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_with_resolver_exception_sends_identity_error_reply() -> None:
    update = _make_update(from_user_id="12345678", text="/start", chat_id="chat_D")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply()

    class ExplodingResolver:
        async def resolve_telegram_identity(self, telegram_user_id: str) -> TelegramIdentityResolution:
            raise RuntimeError("resolver exploded")

    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=ExplodingResolver(),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert len(adapter.replies) == 1
    assert adapter.replies[0][1] == _REPLY_IDENTITY_ERROR
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_no_resolver_uses_staging_fallback() -> None:
    update = _make_update(from_user_id="12345678", text="/start")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply("Welcome!")
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=None,
        staging_tenant_id="staging",
        staging_user_id="staging",
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    dispatcher.dispatch.assert_awaited_once()
    dispatched_ctx: TelegramCommandContext = dispatcher.dispatch.call_args[0][0]
    assert dispatched_ctx.tenant_id == "staging"
    assert dispatched_ctx.user_id == "staging"


def test_polling_loop_resolver_called_with_correct_from_user_id() -> None:
    update = _make_update(from_user_id="42000000", text="/start")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply()
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="resolved", tenant_id="t1", user_id="usr_x")
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert resolver.calls == ["42000000"]


def test_polling_loop_resolver_skipped_for_non_command_messages() -> None:
    update = _make_update(from_user_id="12345678", text="hello world")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply()
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="resolved", tenant_id="t1", user_id="usr_abc")
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert resolver.calls == []
    dispatcher.dispatch.assert_not_awaited()
    assert adapter.replies == []


def test_polling_loop_resolved_with_missing_tenant_id_sends_identity_error() -> None:
    update = _make_update(from_user_id="12345678", text="/start", chat_id="chat_E")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply("Welcome!")
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="resolved", tenant_id=None, user_id="usr_abc")
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert len(adapter.replies) == 1
    assert adapter.replies[0] == ("chat_E", _REPLY_IDENTITY_ERROR)
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_resolved_with_missing_user_id_sends_identity_error() -> None:
    update = _make_update(from_user_id="12345678", text="/start", chat_id="chat_F")
    adapter = MockTelegramAdapter(updates=[update])
    dispatcher = _make_dispatcher_with_start_reply("Welcome!")
    resolver = MockIdentityResolver(
        TelegramIdentityResolution(outcome="resolved", tenant_id="t1", user_id=None)
    )
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=resolver,
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())

    assert len(adapter.replies) == 1
    assert adapter.replies[0] == ("chat_F", _REPLY_IDENTITY_ERROR)
    dispatcher.dispatch.assert_not_awaited()
