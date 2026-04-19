"""Phase 8.13 — Telegram session-issuance handoff foundation tests.

Contract under test:
- activation_status == "active"  -> session_issued (session issued, no state mutation)
- activation_status != "active"  -> rejected (no session, no state mutation)
- unlinked user                  -> rejected
- pending_confirmation user does NOT become active as side effect
- tenant isolation preserved across persistent store reloads
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    CrusaderBackendClient,
    TelegramIdentityResolution,
    TelegramSessionIssuanceResult,
)
from projects.polymarket.polyquantbot.client.telegram.dispatcher import DispatchResult, TelegramDispatcher
from projects.polymarket.polyquantbot.client.telegram.runtime import (
    TelegramInboundUpdate,
    TelegramPollingLoop,
    TelegramRuntimeAdapter,
    _REPLY_ACTIVATION_REJECTED,
    _REPLY_ALREADY_ACTIVE_SESSION_ISSUED,
    _REPLY_IDENTITY_ERROR,
    _REPLY_SESSION_ISSUED,
)
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService
from projects.polymarket.polyquantbot.server.services.telegram_activation_service import (
    TelegramActivationService,
)
from projects.polymarket.polyquantbot.server.services.telegram_onboarding_service import TelegramOnboardingService
from projects.polymarket.polyquantbot.server.services.telegram_session_issuance_service import (
    TelegramSessionIssuanceService,
)
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.storage.in_memory_store import InMemoryMultiUserStore
from projects.polymarket.polyquantbot.server.storage.multi_user_store import PersistentMultiUserStore
from projects.polymarket.polyquantbot.server.storage.session_store import SessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}

    def get_session(self, session_id: str):
        return self._sessions.get(session_id)

    def put_session(self, session) -> None:
        self._sessions[session.session_id] = session

    def set_session_status(self, session_id: str, status: str):
        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"session not found: {session_id}")
        updated = session.model_copy(update={"status": status})
        self._sessions[session_id] = updated
        return updated


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


class MockSessionIssuer:
    def __init__(self, result: TelegramSessionIssuanceResult) -> None:
        self._result = result

    async def issue_telegram_session(
        self, telegram_user_id: str, ttl_seconds: int = 1800
    ) -> TelegramSessionIssuanceResult:
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


def _make_app(monkeypatch, tmp_path):
    create_app = pytest.importorskip("projects.polymarket.polyquantbot.server.main").create_app
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("CRUSADER_MULTI_USER_STORAGE_PATH", str(tmp_path / "multi_user.json"))
    monkeypatch.setenv("CRUSADER_WALLET_LINK_STORAGE_PATH", str(tmp_path / "wallet_links.json"))
    return create_app()


def _make_services(store=None):
    """Return (user_service, onboarding_service, activation_service, issuance_service)."""
    if store is None:
        store = InMemoryMultiUserStore()
    user_service = UserService(store=store)
    onboarding_service = TelegramOnboardingService(user_service=user_service)
    activation_service = TelegramActivationService(user_service=user_service)
    auth_session_service = AuthSessionService(
        store=store,
        session_store=InMemorySessionStore(),
    )
    issuance_service = TelegramSessionIssuanceService(
        user_service=user_service,
        auth_session_service=auth_session_service,
    )
    return user_service, onboarding_service, activation_service, issuance_service


# ---------------------------------------------------------------------------
# Service unit tests — correct contract
# ---------------------------------------------------------------------------

def test_session_issuance_service_active_user_session_issued() -> None:
    """Active user (via activation service) receives session_issued."""
    user_service, onboarding_service, activation_service, issuance_service = _make_services()

    onboard = onboarding_service.start(telegram_user_id="12345678", tenant_id="t1")
    assert onboard.outcome == "onboarded"

    # Activate user via TelegramActivationService (separate Phase 8.12 service)
    activated = activation_service.confirm(telegram_user_id="12345678", tenant_id="t1")
    assert activated.outcome == "activated"

    # Now issue session — must succeed
    issued = issuance_service.issue(telegram_user_id="12345678", tenant_id="t1")
    assert issued.outcome == "session_issued"
    assert issued.session_id


def test_session_issuance_service_already_active_path_allowed() -> None:
    """Active user calling issue() multiple times always gets session_issued (allowed path)."""
    user_service, onboarding_service, activation_service, issuance_service = _make_services()

    onboard = onboarding_service.start(telegram_user_id="12345678", tenant_id="t1")
    assert onboard.outcome == "onboarded"
    activated = activation_service.confirm(telegram_user_id="12345678", tenant_id="t1")
    assert activated.outcome == "activated"

    first = issuance_service.issue(telegram_user_id="12345678", tenant_id="t1")
    second = issuance_service.issue(telegram_user_id="12345678", tenant_id="t1")
    assert first.outcome == "session_issued"
    assert second.outcome == "session_issued"
    assert first.session_id
    assert second.session_id
    # Each call issues a distinct session
    assert first.session_id != second.session_id


def test_session_issuance_service_pending_confirmation_rejected() -> None:
    """pending_confirmation user is rejected — no session issued."""
    user_service, onboarding_service, activation_service, issuance_service = _make_services()

    onboard = onboarding_service.start(telegram_user_id="12345678", tenant_id="t1")
    assert onboard.outcome == "onboarded"

    # User is pending_confirmation; do NOT call activation_service.confirm()
    issued = issuance_service.issue(telegram_user_id="12345678", tenant_id="t1")
    assert issued.outcome == "rejected"
    assert issued.session_id is None


def test_session_issuance_service_pending_does_not_become_active() -> None:
    """Calling issue() on a pending_confirmation user must not mutate activation_status."""
    user_service, onboarding_service, activation_service, issuance_service = _make_services()

    onboard = onboarding_service.start(telegram_user_id="12345678", tenant_id="t1")
    assert onboard.outcome == "onboarded"
    assert onboard.user_id

    before = user_service.get_user_settings(onboard.user_id)
    assert before is not None
    assert before.activation_status == "pending_confirmation"

    # Attempt to issue session — must be rejected
    issued = issuance_service.issue(telegram_user_id="12345678", tenant_id="t1")
    assert issued.outcome == "rejected"

    # Activation status must remain unchanged — no side-effect mutation
    after = user_service.get_user_settings(onboard.user_id)
    assert after is not None
    assert after.activation_status == "pending_confirmation"


def test_session_issuance_service_rejected_not_linked() -> None:
    """Unlinked user is rejected."""
    user_service, onboarding_service, activation_service, issuance_service = _make_services()

    result = issuance_service.issue(telegram_user_id="12345678", tenant_id="t1")
    assert result.outcome == "rejected"


def test_session_issuance_service_tenant_isolation(tmp_path: Path) -> None:
    """Activation and issuance are isolated per tenant."""
    storage_path = tmp_path / "multi_user.json"

    # Tenant t1: onboard + activate + issue
    store_a = PersistentMultiUserStore(storage_path=storage_path)
    user_service_a = UserService(store=store_a)
    onboarding_a = TelegramOnboardingService(user_service=user_service_a)
    activation_a = TelegramActivationService(user_service=user_service_a)
    auth_session_a = AuthSessionService(store=store_a, session_store=InMemorySessionStore())
    issuance_a = TelegramSessionIssuanceService(
        user_service=user_service_a, auth_session_service=auth_session_a
    )

    ob_t1 = onboarding_a.start(telegram_user_id="12345678", tenant_id="t1")
    assert ob_t1.outcome == "onboarded"
    activation_a.confirm(telegram_user_id="12345678", tenant_id="t1")
    result_t1 = issuance_a.issue("12345678", "t1")
    assert result_t1.outcome == "session_issued"

    # Tenant t2 (same telegram_user_id): separate lifecycle — still pending
    store_b = PersistentMultiUserStore(storage_path=storage_path)
    user_service_b = UserService(store=store_b)
    onboarding_b = TelegramOnboardingService(user_service=user_service_b)
    auth_session_b = AuthSessionService(store=store_b, session_store=InMemorySessionStore())
    issuance_b = TelegramSessionIssuanceService(
        user_service=user_service_b, auth_session_service=auth_session_b
    )

    ob_t2 = onboarding_b.start(telegram_user_id="12345678", tenant_id="t2")
    assert ob_t2.outcome == "onboarded"
    # t2 user is pending — not activated
    result_t2 = issuance_b.issue("12345678", "t2")
    assert result_t2.outcome == "rejected"

    # Verify t1 state is unaffected by t2 rejection
    settings_t1 = UserService(
        store=PersistentMultiUserStore(storage_path=storage_path)
    ).get_user_settings(ob_t1.user_id or "")
    assert settings_t1 is not None
    assert settings_t1.activation_status == "active"

    # Verify t2 state is still pending (no cross-tenant mutation)
    settings_t2 = UserService(
        store=PersistentMultiUserStore(storage_path=storage_path)
    ).get_user_settings(ob_t2.user_id or "")
    assert settings_t2 is not None
    assert settings_t2.activation_status == "pending_confirmation"


# ---------------------------------------------------------------------------
# Backend client mapping test
# ---------------------------------------------------------------------------

def test_backend_client_issue_session_http_success() -> None:
    client = CrusaderBackendClient(base_url="http://localhost:8080", identity_tenant_id="t1")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "outcome": "session_issued",
        "tenant_id": "t1",
        "user_id": "usr_abc",
        "session_id": "sess_abc",
        "detail": "",
    }

    async def run() -> TelegramSessionIssuanceResult:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_http
            return await client.issue_telegram_session("12345678")

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result.outcome == "session_issued"
    assert result.session_id == "sess_abc"


# ---------------------------------------------------------------------------
# Runtime reply mapping tests (mock-based — do not call service directly)
# ---------------------------------------------------------------------------

def test_polling_loop_session_issued_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        session_issuer=MockSessionIssuer(
            TelegramSessionIssuanceResult(outcome="session_issued", tenant_id="t1", user_id="usr_1")
        ),
    )
    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_SESSION_ISSUED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_already_active_session_issued_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        session_issuer=MockSessionIssuer(
            TelegramSessionIssuanceResult(
                outcome="already_active_session_issued", tenant_id="t1", user_id="usr_1"
            )
        ),
    )
    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_ALREADY_ACTIVE_SESSION_ISSUED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_session_issuance_rejected_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        session_issuer=MockSessionIssuer(TelegramSessionIssuanceResult(outcome="rejected")),
    )
    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_ACTIVATION_REJECTED
    dispatcher.dispatch.assert_not_awaited()


def test_polling_loop_session_issuance_error_reply() -> None:
    adapter = MockTelegramAdapter(updates=[_make_update()])
    dispatcher = _make_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        identity_resolver=MockResolvedIdentityResolver(),
        session_issuer=MockSessionIssuer(TelegramSessionIssuanceResult(outcome="error")),
    )
    asyncio.get_event_loop().run_until_complete(loop.run_once())
    assert adapter.replies[0][1] == _REPLY_IDENTITY_ERROR
    dispatcher.dispatch.assert_not_awaited()


# ---------------------------------------------------------------------------
# Integration route tests (fastapi.testclient via importorskip)
# ---------------------------------------------------------------------------

def test_integration_route_telegram_session_issue_active_user(monkeypatch, tmp_path) -> None:
    """Active user (onboarded + confirmed) gets session_issued from the route."""
    TestClient = pytest.importorskip("fastapi.testclient").TestClient
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        # Step 1: onboard
        start_resp = client.post(
            "/auth/telegram-onboarding/start",
            json={"telegram_user_id": "10101", "tenant_id": "t-int"},
        )
        assert start_resp.status_code == 200
        assert start_resp.json()["outcome"] == "onboarded"

        # Step 2: activate (Phase 8.12)
        confirm_resp = client.post(
            "/auth/telegram-onboarding/confirm",
            json={"telegram_user_id": "10101", "tenant_id": "t-int"},
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["outcome"] == "activated"

        # Step 3: issue session — must succeed
        first_issue = client.post(
            "/auth/telegram-onboarding/session-issue",
            json={"telegram_user_id": "10101", "tenant_id": "t-int"},
        )
        assert first_issue.status_code == 200
        assert first_issue.json()["outcome"] == "session_issued"
        assert first_issue.json()["session_id"]

        # Step 4: issue again — still allowed
        second_issue = client.post(
            "/auth/telegram-onboarding/session-issue",
            json={"telegram_user_id": "10101", "tenant_id": "t-int"},
        )
        assert second_issue.status_code == 200
        assert second_issue.json()["outcome"] == "session_issued"
        assert second_issue.json()["session_id"]


def test_integration_route_telegram_session_issue_pending_rejected(monkeypatch, tmp_path) -> None:
    """pending_confirmation user (onboarded but NOT confirmed) is rejected."""
    TestClient = pytest.importorskip("fastapi.testclient").TestClient
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        # Onboard only — do NOT confirm activation
        start_resp = client.post(
            "/auth/telegram-onboarding/start",
            json={"telegram_user_id": "20202", "tenant_id": "t-int"},
        )
        assert start_resp.status_code == 200
        assert start_resp.json()["outcome"] == "onboarded"

        # Attempt to issue session — must be rejected
        issue_resp = client.post(
            "/auth/telegram-onboarding/session-issue",
            json={"telegram_user_id": "20202", "tenant_id": "t-int"},
        )
        assert issue_resp.status_code == 200
        assert issue_resp.json()["outcome"] == "rejected"


def test_integration_route_telegram_session_issue_unlinked_rejected(monkeypatch, tmp_path) -> None:
    """Unlinked user is rejected at the session-issue route."""
    TestClient = pytest.importorskip("fastapi.testclient").TestClient
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        issue_resp = client.post(
            "/auth/telegram-onboarding/session-issue",
            json={"telegram_user_id": "not-linked", "tenant_id": "t-int"},
        )
        assert issue_resp.status_code == 200
        assert issue_resp.json()["outcome"] == "rejected"
