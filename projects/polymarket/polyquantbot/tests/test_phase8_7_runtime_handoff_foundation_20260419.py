"""Phase 8.7 — Telegram/Web Runtime Handoff Integration Foundation tests."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    BackendHandoffRequest,
    BackendHandoffResult,
    CrusaderBackendClient,
)
from projects.polymarket.polyquantbot.client.telegram.handlers.auth import (
    HandleStartResult,
    TelegramHandoffContext,
    handle_start,
)
from projects.polymarket.polyquantbot.client.web.handoff import (
    WebHandoffContext,
    WebHandoffResult,
    handle_web_handoff,
)
from projects.polymarket.polyquantbot.server.main import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_backend(outcome: str, session_id: str = "sess-test", detail: str = "") -> CrusaderBackendClient:
    """Return a CrusaderBackendClient with request_handoff mocked to return fixed result."""
    backend = MagicMock(spec=CrusaderBackendClient)
    backend.request_handoff = AsyncMock(
        return_value=BackendHandoffResult(outcome=outcome, session_id=session_id, detail=detail)
    )
    return backend


def _make_app(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_SESSION_STORAGE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("CRUSADER_MULTI_USER_STORAGE_PATH", str(tmp_path / "multi_user.json"))
    monkeypatch.setenv("CRUSADER_WALLET_LINK_STORAGE_PATH", str(tmp_path / "wallet_links.json"))
    return create_app()


# ---------------------------------------------------------------------------
# Unit tests — Telegram handle_start with mocked backend
# ---------------------------------------------------------------------------


def test_telegram_handle_start_session_issued() -> None:
    backend = _make_mock_backend(outcome="issued", session_id="sess-tg-001")
    context = TelegramHandoffContext(
        telegram_user_id="123456",
        chat_id="chat-001",
        tenant_id="t-alpha",
        user_id="usr-001",
    )
    result: HandleStartResult = asyncio.run(handle_start(context=context, backend=backend))
    assert result.outcome == "session_issued"
    assert result.session_id == "sess-tg-001"
    assert result.reply_text
    backend.request_handoff.assert_awaited_once()
    call_arg: BackendHandoffRequest = backend.request_handoff.call_args[0][0]
    assert call_arg.client_type == "telegram"
    assert call_arg.client_identity_claim == "123456"


def test_telegram_handle_start_rejected_empty_user_id() -> None:
    backend = _make_mock_backend(outcome="issued")
    context = TelegramHandoffContext(
        telegram_user_id="",
        chat_id="chat-002",
        tenant_id="t-alpha",
        user_id="usr-001",
    )
    result: HandleStartResult = asyncio.run(handle_start(context=context, backend=backend))
    assert result.outcome == "rejected"
    backend.request_handoff.assert_not_awaited()


def test_telegram_handle_start_whitespace_user_id_rejected() -> None:
    backend = _make_mock_backend(outcome="issued")
    context = TelegramHandoffContext(
        telegram_user_id="   ",
        chat_id="chat-003",
        tenant_id="t-alpha",
        user_id="usr-001",
    )
    result: HandleStartResult = asyncio.run(handle_start(context=context, backend=backend))
    assert result.outcome == "rejected"
    backend.request_handoff.assert_not_awaited()


def test_telegram_handle_start_backend_rejected() -> None:
    backend = _make_mock_backend(outcome="rejected", detail="user not found: usr-999")
    context = TelegramHandoffContext(
        telegram_user_id="777",
        chat_id="chat-004",
        tenant_id="t-alpha",
        user_id="usr-999",
    )
    result: HandleStartResult = asyncio.run(handle_start(context=context, backend=backend))
    assert result.outcome == "rejected"
    assert "usr-999" in result.reply_text


def test_telegram_handle_start_backend_error() -> None:
    backend = _make_mock_backend(outcome="error", detail="connection refused")
    context = TelegramHandoffContext(
        telegram_user_id="888",
        chat_id="chat-005",
        tenant_id="t-alpha",
        user_id="usr-001",
    )
    result: HandleStartResult = asyncio.run(handle_start(context=context, backend=backend))
    assert result.outcome == "error"
    assert result.reply_text


# ---------------------------------------------------------------------------
# Unit tests — BackendHandoffRequest pre-validation in CrusaderBackendClient
# ---------------------------------------------------------------------------


def test_backend_client_rejects_empty_claim() -> None:
    client = CrusaderBackendClient(base_url="http://localhost:8080")
    request = BackendHandoffRequest(
        client_type="telegram",
        client_identity_claim="",
        tenant_id="t-alpha",
        user_id="usr-001",
    )
    result: BackendHandoffResult = asyncio.run(client.request_handoff(request))
    assert result.outcome == "rejected"
    assert "empty" in result.detail


def test_backend_client_rejects_unsupported_client_type() -> None:
    client = CrusaderBackendClient(base_url="http://localhost:8080")
    request = BackendHandoffRequest(
        client_type="discord",
        client_identity_claim="abc",
        tenant_id="t-alpha",
        user_id="usr-001",
    )
    result: BackendHandoffResult = asyncio.run(client.request_handoff(request))
    assert result.outcome == "rejected"
    assert "unsupported" in result.detail


def test_backend_client_rejects_empty_tenant_id() -> None:
    client = CrusaderBackendClient(base_url="http://localhost:8080")
    request = BackendHandoffRequest(
        client_type="telegram",
        client_identity_claim="tg_123",
        tenant_id="",
        user_id="usr-001",
    )
    result: BackendHandoffResult = asyncio.run(client.request_handoff(request))
    assert result.outcome == "rejected"
    assert "empty" in result.detail


# ---------------------------------------------------------------------------
# Unit tests — Web handle_web_handoff with mocked backend
# ---------------------------------------------------------------------------


def test_web_handoff_session_issued() -> None:
    backend = _make_mock_backend(outcome="issued", session_id="sess-web-001")
    context = WebHandoffContext(
        client_identity_claim="web_user_abc",
        tenant_id="t-beta",
        user_id="usr-002",
    )
    result: WebHandoffResult = asyncio.run(handle_web_handoff(context=context, backend=backend))
    assert result.outcome == "session_issued"
    assert result.session_id == "sess-web-001"
    backend.request_handoff.assert_awaited_once()
    call_arg: BackendHandoffRequest = backend.request_handoff.call_args[0][0]
    assert call_arg.client_type == "web"
    assert call_arg.client_identity_claim == "web_user_abc"


def test_web_handoff_rejected_empty_claim() -> None:
    backend = _make_mock_backend(outcome="issued")
    context = WebHandoffContext(
        client_identity_claim="",
        tenant_id="t-beta",
        user_id="usr-002",
    )
    result: WebHandoffResult = asyncio.run(handle_web_handoff(context=context, backend=backend))
    assert result.outcome == "rejected"
    backend.request_handoff.assert_not_awaited()


def test_web_handoff_backend_rejected() -> None:
    backend = _make_mock_backend(outcome="rejected", detail="user not found: usr-888")
    context = WebHandoffContext(
        client_identity_claim="web_user_xyz",
        tenant_id="t-beta",
        user_id="usr-888",
    )
    result: WebHandoffResult = asyncio.run(handle_web_handoff(context=context, backend=backend))
    assert result.outcome == "rejected"
    assert result.detail


def test_web_handoff_backend_error() -> None:
    backend = _make_mock_backend(outcome="error", detail="upstream timeout")
    context = WebHandoffContext(
        client_identity_claim="web_user_xyz",
        tenant_id="t-beta",
        user_id="usr-002",
    )
    result: WebHandoffResult = asyncio.run(handle_web_handoff(context=context, backend=backend))
    assert result.outcome == "error"
    assert result.detail


# ---------------------------------------------------------------------------
# Integration tests — real backend via TestClient (Telegram + Web flows)
# ---------------------------------------------------------------------------


def test_integration_telegram_handoff_session_issued(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        user_resp = client.post(
            "/foundation/users",
            json={"tenant_id": "t-tg-int", "external_id": "tg_87001"},
        )
        assert user_resp.status_code == 200
        user_id = user_resp.json()["user"]["user_id"]

        handoff_resp = client.post(
            "/auth/handoff",
            json={
                "client_type": "telegram",
                "client_identity_claim": "tg_87001",
                "tenant_id": "t-tg-int",
                "user_id": user_id,
            },
        )
        assert handoff_resp.status_code == 200
        data = handoff_resp.json()
        assert data["session"]["session_id"]
        assert data["scope"]["auth_method"] == "telegram"


def test_integration_web_handoff_session_issued(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        user_resp = client.post(
            "/foundation/users",
            json={"tenant_id": "t-web-int", "external_id": "web_87002"},
        )
        assert user_resp.status_code == 200
        user_id = user_resp.json()["user"]["user_id"]

        handoff_resp = client.post(
            "/auth/handoff",
            json={
                "client_type": "web",
                "client_identity_claim": "web_87002",
                "tenant_id": "t-web-int",
                "user_id": user_id,
            },
        )
        assert handoff_resp.status_code == 200
        data = handoff_resp.json()
        assert data["session"]["session_id"]
        assert data["scope"]["auth_method"] == "web"


def test_integration_telegram_handoff_unknown_user_rejected(monkeypatch, tmp_path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        handoff_resp = client.post(
            "/auth/handoff",
            json={
                "client_type": "telegram",
                "client_identity_claim": "tg_nobody",
                "tenant_id": "t-tg-int",
                "user_id": "usr-does-not-exist",
            },
        )
        assert handoff_resp.status_code == 400


def test_integration_telegram_session_usable_in_authenticated_route(monkeypatch, tmp_path) -> None:
    """Full integration: user registered -> telegram handoff -> session used in wallet-link route."""
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        user_resp = client.post(
            "/foundation/users",
            json={"tenant_id": "t-tg-full", "external_id": "tg_87003"},
        )
        user_id = user_resp.json()["user"]["user_id"]

        handoff_resp = client.post(
            "/auth/handoff",
            json={
                "client_type": "telegram",
                "client_identity_claim": "tg_87003",
                "tenant_id": "t-tg-full",
                "user_id": user_id,
            },
        )
        assert handoff_resp.status_code == 200
        session_id = handoff_resp.json()["session"]["session_id"]

        links_resp = client.get(
            "/auth/wallet-links",
            headers={
                "X-Session-Id": session_id,
                "X-Auth-Tenant-Id": "t-tg-full",
                "X-Auth-User-Id": user_id,
            },
        )
        assert links_resp.status_code == 200
        assert "wallet_links" in links_resp.json()
