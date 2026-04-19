"""Phase 8.12 — Telegram confirmation/activation foundation tests."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    CrusaderBackendClient,
    TelegramActivationResult,
    TelegramIdentityResolution,
)
from projects.polymarket.polyquantbot.client.telegram.dispatcher import DispatchResult, TelegramDispatcher
from projects.polymarket.polyquantbot.client.telegram.runtime import (
    TelegramInboundUpdate,
    TelegramPollingLoop,
    TelegramRuntimeAdapter,
    _REPLY_ACTIVATED,
    _REPLY_ACTIVATION_REJECTED,
    _REPLY_IDENTITY_ERROR,
)
from projects.polymarket.polyquantbot.server.services.telegram_activation_service import TelegramActivationService
from projects.polymarket.polyquantbot.server.services.telegram_onboarding_service import TelegramOnboardingService
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


class MockResolvedIdentityResolver:
    async def resolve_telegram_identity(self, telegram_user_id: str) -> TelegramIdentityResolution:
        return TelegramIdentityResolution(outcome="resolved", tenant_id="t1", user_id="usr_1")


class MockActivationConfirmer:
    def __init__(self, result: TelegramActivationResult) -> None:
        self._result = result

    async def confirm_telegram_activation(self, telegram_user_id: str) -> TelegramActivationResult:
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


def test_activation_service_success_transition_to_active() -> None:
    store = InMemoryMultiUserStore()
    user_service = UserService(store=store)
    onboarding_service = TelegramOnboardingService(user_service=user_service)
    activation_service = TelegramActivationService(user_service=user_service)

    onboard = onboarding_service.start(telegram_user_id="12345678", tenant_id="t1")
    assert onboard.outcome == "onboarded"

    confirm = activation_service.confirm(telegram_user_id="12345678", tenant_id="t1")
    assert confirm.outcome == "activated"

    settings = user_service.get_user_settings(onboard.user_id or "")
    assert settings is not None
    assert settings.activation_status == "active"


def test_activation_service_already_active_path() -> None:
    store = InMemoryMultiUserStore()
    user_service = UserService(store=store)
    onboarding_service = TelegramOnboardingService(user_service=user_service)
    activation_service = TelegramActivationService(user_service=user_service)

    onboard = onboarding_service.start(telegram_user_id="12345678", tenant_id="t1")
    assert onboard.outcome == "onboarded"
    first = activation_service.confirm(telegram_user_id="12345678", tenant_id="t1")
    second = activation_service.confirm(telegram_user_id="12345678", tenant_id="t1")

    assert first.outcome == "activated"
    assert second.outcome == "already_active"


def test_activation_service_rejected_path_not_linked() -> None:
    activation_service = TelegramActivationService(
        user_service=UserService(store=InMemoryMultiUserStore())
    )
    result = activation_service.confirm(telegram_user_id="12345678", tenant_id="t1")
    assert result.outcome == "rejected"


def test_activation_service_error_path_store_exception() -> None:
    user_service = UserService(store=InMemoryMultiUserStore())

    def raise_error(tenant_id: str, external_id: str) -> None:
        raise RuntimeError("forced activation failure")

    user_service.get_user_by_external_id = raise_error  # type: ignore[method-assign]
    activation_service = TelegramActivationService(user_service=user_service)
    result = activation_service.confirm(telegram_user_id="12345678", tenant_id="t1")
    assert result.outcome == "error"


def test_activation_service_persistence_and_tenant_isolation(tmp_path: Path) -> None:
    storage_path = tmp_path / "multi_user.json"
    user_service_a = UserService(store=PersistentMultiUserStore(storage_path=storage_path))
    onboarding_service_a = TelegramOnboardingService(user_service=user_service_a)
    activation_service_a = TelegramActivationService(user_service=user_service_a)

    onboard_t1 = onboarding_service_a.start(telegram_user_id="12345678", tenant_id="t1")
    assert onboard_t1.outcome == "onboarded"
    activated_t1 = activation_service_a.confirm(telegram_user_id="12345678", tenant_id="t1")
    assert activated_t1.outcome == "activated"

    user_service_b = UserService(store=PersistentMultiUserStore(storage_path=storage_path))
    onboarding_service_b = TelegramOnboardingService(user_service=user_service_b)
    activation_service_b = TelegramActivationService(user_service=user_service_b)

    onboard_t2 = onboarding_service_b.start(telegram_user_id="12345678", tenant_id="t2")
    assert onboard_t2.outcome == "onboarded"
    activated_t2 = activation_service_b.confirm(telegram_user_id="12345678", tenant_id="t2")
    assert activated_t2.outcome == "activated"

    verify = UserService(store=PersistentMultiUserStore(storage_path=storage_path))
    settings_t1 = verify.get_user_settings(onboard_t1.user_id or "")
    settings_t2 = verify.get_user_settings(onboard_t2.user_id or "")
    assert settings_t1 is not None and settings_t1.activation_status == "active"
    assert settings_t2 is not None and settings_t2.activation_status == "active"


def test_backend_client_confirm_activation_http_success() -> None:
    client = CrusaderBackendClient(base_url="http://localhost:8080", identity_tenant_id="t1")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "outcome": "activated",
        "tenant_id": "t1",
        "user_id": "usr_abc",
        "detail": "",
    }

    async def run() -> TelegramActivationResult:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_http
            return await client.confirm_telegram_activation("12345678")

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result.outcome == "activated"
    assert result.user_id == "usr_abc"


def test_polling_loop_resolved_activation_activated_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        activation_confirmer=MockActivationConfirmer(
            TelegramActivationResult(outcome="activated", tenant_id="t1", user_id="usr_1")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_ACTIVATED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_resolved_activation_already_active_dispatches() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        activation_confirmer=MockActivationConfirmer(
            TelegramActivationResult(outcome="already_active", tenant_id="t1", user_id="usr_1")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == "Welcome!"
    dispatcher.dispatch.assert_awaited_once()


def test_polling_loop_resolved_activation_rejected_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        activation_confirmer=MockActivationConfirmer(
            TelegramActivationResult(outcome="rejected", detail="denied")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_ACTIVATION_REJECTED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_resolved_activation_error_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        activation_confirmer=MockActivationConfirmer(
            TelegramActivationResult(outcome="error", detail="backend error")
        ),
    )

    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_IDENTITY_ERROR
    dispatcher.dispatch.assert_not_awaited()
