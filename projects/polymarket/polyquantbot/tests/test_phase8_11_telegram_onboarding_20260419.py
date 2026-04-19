"""Phase 8.11 — Telegram onboarding/account-link foundation tests."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    CrusaderBackendClient,
    TelegramIdentityResolution,
    TelegramOnboardingResult,
)
from projects.polymarket.polyquantbot.client.telegram.dispatcher import DispatchResult, TelegramDispatcher
from projects.polymarket.polyquantbot.client.telegram.runtime import (
    TelegramInboundUpdate,
    TelegramPollingLoop,
    TelegramRuntimeAdapter,
    _REPLY_ALREADY_LINKED,
    _REPLY_IDENTITY_ERROR,
    _REPLY_ONBOARDED,
    _REPLY_ONBOARDING_REJECTED,
)
from projects.polymarket.polyquantbot.server.services.telegram_onboarding_service import (
    TELEGRAM_EXTERNAL_ID_PREFIX,
    TelegramOnboardingService,
)
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.storage.in_memory_store import InMemoryMultiUserStore
from projects.polymarket.polyquantbot.server.storage.multi_user_store import PersistentMultiUserStore


class MockTelegramAdapter(TelegramRuntimeAdapter):
    def __init__(self, updates: list[TelegramInboundUpdate]) -> None:
        self._updates = updates
        self.replies: list[tuple[str, str]] = []

    async def get_updates(self, offset: int = 0, limit: int = 100) -> list[TelegramInboundUpdate]:
        return [u for u in self._updates if u.update_id >= offset]

    async def send_reply(self, chat_id: str, text: str) -> None:
        self.replies.append((chat_id, text))


class MockIdentityResolver:
    async def resolve_telegram_identity(self, telegram_user_id: str) -> TelegramIdentityResolution:
        return TelegramIdentityResolution(outcome="not_found")


class MockOnboardingInitiator:
    def __init__(self, result: TelegramOnboardingResult) -> None:
        self._result = result

    async def start_telegram_onboarding(self, telegram_user_id: str) -> TelegramOnboardingResult:
        return self._result


def _make_update() -> TelegramInboundUpdate:
    return TelegramInboundUpdate(
        update_id=1,
        chat_id="chat_001",
        from_user_id="12345678",
        text="/start",
    )


def _make_dispatcher() -> TelegramDispatcher:
    dispatcher = MagicMock(spec=TelegramDispatcher)
    dispatcher.dispatch = AsyncMock(
        return_value=DispatchResult(
            outcome="session_issued",
            reply_text="Welcome!",
            session_id="sess_1",
        )
    )
    return dispatcher


def test_onboarding_service_success_creates_user() -> None:
    store = InMemoryMultiUserStore()
    service = TelegramOnboardingService(user_service=UserService(store=store))

    result = service.start(telegram_user_id="12345678", tenant_id="t1")

    assert result.outcome == "onboarded"
    assert result.user_id is not None
    created = store.get_user(result.user_id)
    assert created is not None
    assert created.tenant_id == "t1"
    assert created.external_id == f"{TELEGRAM_EXTERNAL_ID_PREFIX}12345678"


def test_onboarding_service_already_linked_path() -> None:
    store = InMemoryMultiUserStore()
    service = TelegramOnboardingService(user_service=UserService(store=store))

    first = service.start(telegram_user_id="12345678", tenant_id="t1")
    second = service.start(telegram_user_id="12345678", tenant_id="t1")

    assert first.outcome == "onboarded"
    assert second.outcome == "already_linked"
    assert second.user_id == first.user_id


def test_onboarding_service_rejected_path_empty_id() -> None:
    service = TelegramOnboardingService(user_service=UserService(store=InMemoryMultiUserStore()))
    result = service.start(telegram_user_id="", tenant_id="t1")
    assert result.outcome == "rejected"


def test_onboarding_service_error_path_store_exception() -> None:
    user_service = UserService(store=InMemoryMultiUserStore())

    def raise_error(tenant_id: str, external_id: str) -> None:
        raise RuntimeError("forced failure")

    user_service.get_user_by_external_id = raise_error  # type: ignore[method-assign]
    service = TelegramOnboardingService(user_service=user_service)
    result = service.start(telegram_user_id="12345678", tenant_id="t1")
    assert result.outcome == "error"


def test_onboarding_service_persistence_and_tenant_isolation(tmp_path: Path) -> None:
    storage_path = tmp_path / "multi_user.json"
    service_a = TelegramOnboardingService(
        user_service=UserService(store=PersistentMultiUserStore(storage_path=storage_path))
    )
    result_t1 = service_a.start(telegram_user_id="12345678", tenant_id="t1")
    assert result_t1.outcome == "onboarded"

    service_b = TelegramOnboardingService(
        user_service=UserService(store=PersistentMultiUserStore(storage_path=storage_path))
    )
    result_t2 = service_b.start(telegram_user_id="12345678", tenant_id="t2")
    assert result_t2.outcome == "onboarded"
    assert result_t2.user_id != result_t1.user_id

    store_verify = PersistentMultiUserStore(storage_path=storage_path)
    assert store_verify.get_user(result_t1.user_id or "") is not None
    assert store_verify.get_user(result_t2.user_id or "") is not None


def test_backend_client_start_onboarding_http_success() -> None:
    client = CrusaderBackendClient(base_url="http://localhost:8080", identity_tenant_id="t1")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "outcome": "onboarded",
        "tenant_id": "t1",
        "user_id": "usr_abc",
        "detail": "",
    }

    async def run() -> TelegramOnboardingResult:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_http
            return await client.start_telegram_onboarding("12345678")

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result.outcome == "onboarded"
    assert result.user_id == "usr_abc"


def test_polling_loop_not_found_onboarded_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockIdentityResolver(),
        onboarding_initiator=MockOnboardingInitiator(
            TelegramOnboardingResult(outcome="onboarded", tenant_id="t1", user_id="usr_1")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_ONBOARDED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_not_found_already_linked_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockIdentityResolver(),
        onboarding_initiator=MockOnboardingInitiator(
            TelegramOnboardingResult(outcome="already_linked", tenant_id="t1", user_id="usr_1")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_ALREADY_LINKED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_not_found_rejected_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockIdentityResolver(),
        onboarding_initiator=MockOnboardingInitiator(
            TelegramOnboardingResult(outcome="rejected", detail="denied")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_ONBOARDING_REJECTED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_not_found_onboarding_error_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockIdentityResolver(),
        onboarding_initiator=MockOnboardingInitiator(
            TelegramOnboardingResult(outcome="error", detail="backend error")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_IDENTITY_ERROR
    dispatcher.dispatch.assert_not_awaited()
