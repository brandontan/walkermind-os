"""Phase 8.8 — TelegramDispatcher command dispatch boundary tests."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from projects.polymarket.polyquantbot.client.telegram.backend_client import (
    BackendHandoffResult,
    CrusaderBackendClient,
)
from projects.polymarket.polyquantbot.client.telegram.dispatcher import (
    DispatchResult,
    TelegramCommandContext,
    TelegramDispatcher,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_backend(
    outcome: str,
    session_id: str = "sess-test",
    detail: str = "",
) -> CrusaderBackendClient:
    backend = MagicMock(spec=CrusaderBackendClient)
    backend.request_handoff = AsyncMock(
        return_value=BackendHandoffResult(outcome=outcome, session_id=session_id, detail=detail)
    )
    return backend


def _make_ctx(
    command: str = "/start",
    from_user_id: str = "tg_88001",
    chat_id: str = "chat-88-001",
    tenant_id: str = "t-dispatch",
    user_id: str = "usr-dispatch-01",
) -> TelegramCommandContext:
    return TelegramCommandContext(
        command=command,
        from_user_id=from_user_id,
        chat_id=chat_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# /start dispatch — outcome mapping
# ---------------------------------------------------------------------------


def test_dispatch_start_session_issued() -> None:
    backend = _make_mock_backend(outcome="issued", session_id="sess-88-001")
    dispatcher = TelegramDispatcher(backend=backend)
    result: DispatchResult = asyncio.run(dispatcher.dispatch(_make_ctx("/start")))
    assert result.outcome == "session_issued"
    assert result.session_id == "sess-88-001"
    assert result.reply_text
    backend.request_handoff.assert_awaited_once()


def test_dispatch_start_rejected() -> None:
    backend = _make_mock_backend(outcome="rejected", detail="user not found")
    dispatcher = TelegramDispatcher(backend=backend)
    result: DispatchResult = asyncio.run(dispatcher.dispatch(_make_ctx("/start")))
    assert result.outcome == "rejected"
    assert result.reply_text


def test_dispatch_start_backend_error() -> None:
    backend = _make_mock_backend(outcome="error", detail="connection refused")
    dispatcher = TelegramDispatcher(backend=backend)
    result: DispatchResult = asyncio.run(dispatcher.dispatch(_make_ctx("/start")))
    assert result.outcome == "error"
    assert result.reply_text


# ---------------------------------------------------------------------------
# /start dispatch — context mapping to handle_start
# ---------------------------------------------------------------------------


def test_dispatch_start_maps_from_user_id_to_telegram_user_id() -> None:
    """Dispatcher must pass from_user_id as telegram_user_id to handle_start."""
    backend = _make_mock_backend(outcome="issued", session_id="sess-88-002")
    dispatcher = TelegramDispatcher(backend=backend)
    ctx = _make_ctx(command="/start", from_user_id="tg_specific_88002")
    asyncio.run(dispatcher.dispatch(ctx))
    call_arg = backend.request_handoff.call_args[0][0]
    assert call_arg.client_identity_claim == "tg_specific_88002"
    assert call_arg.client_type == "telegram"
    assert call_arg.tenant_id == "t-dispatch"
    assert call_arg.user_id == "usr-dispatch-01"


def test_dispatch_start_empty_from_user_id_rejected() -> None:
    """Empty from_user_id must be rejected — handled by handle_start local check."""
    backend = _make_mock_backend(outcome="issued")
    dispatcher = TelegramDispatcher(backend=backend)
    ctx = _make_ctx(command="/start", from_user_id="")
    result: DispatchResult = asyncio.run(dispatcher.dispatch(ctx))
    assert result.outcome == "rejected"
    backend.request_handoff.assert_not_awaited()


def test_dispatch_start_whitespace_from_user_id_rejected() -> None:
    backend = _make_mock_backend(outcome="issued")
    dispatcher = TelegramDispatcher(backend=backend)
    ctx = _make_ctx(command="/start", from_user_id="   ")
    result: DispatchResult = asyncio.run(dispatcher.dispatch(ctx))
    assert result.outcome == "rejected"
    backend.request_handoff.assert_not_awaited()


# ---------------------------------------------------------------------------
# Unknown command handling
# ---------------------------------------------------------------------------


def test_dispatch_unknown_command() -> None:
    backend = _make_mock_backend(outcome="issued")
    dispatcher = TelegramDispatcher(backend=backend)
    result: DispatchResult = asyncio.run(dispatcher.dispatch(_make_ctx("/unknown")))
    assert result.outcome == "unknown_command"
    assert result.reply_text
    backend.request_handoff.assert_not_awaited()


def test_dispatch_help_command() -> None:
    backend = _make_mock_backend(outcome="issued")
    dispatcher = TelegramDispatcher(backend=backend)
    result: DispatchResult = asyncio.run(dispatcher.dispatch(_make_ctx("/help")))
    assert result.outcome == "ok"
    assert "CrusaderBot commands" in result.reply_text
    backend.request_handoff.assert_not_awaited()


def test_dispatch_unknown_command_empty_string() -> None:
    backend = _make_mock_backend(outcome="issued")
    dispatcher = TelegramDispatcher(backend=backend)
    result: DispatchResult = asyncio.run(dispatcher.dispatch(_make_ctx("")))
    assert result.outcome == "unknown_command"
    backend.request_handoff.assert_not_awaited()


# ---------------------------------------------------------------------------
# Reply text contract — all outcomes must return non-empty reply_text
# ---------------------------------------------------------------------------


def test_dispatch_result_has_reply_text_on_session_issued() -> None:
    backend = _make_mock_backend(outcome="issued", session_id="sess-88-003")
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/start")))
    assert result.reply_text.strip() != ""


def test_dispatch_result_has_reply_text_on_rejected() -> None:
    backend = _make_mock_backend(outcome="rejected", detail="access denied")
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/start")))
    assert result.reply_text.strip() != ""


def test_dispatch_result_has_reply_text_on_error() -> None:
    backend = _make_mock_backend(outcome="error", detail="timeout")
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/start")))
    assert result.reply_text.strip() != ""


def test_dispatch_result_has_reply_text_on_unknown_command() -> None:
    backend = _make_mock_backend(outcome="issued")
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/whatever")))
    assert result.reply_text.strip() != ""


# ---------------------------------------------------------------------------
# Case-insensitive command routing
# ---------------------------------------------------------------------------


def test_dispatch_start_case_insensitive() -> None:
    backend = _make_mock_backend(outcome="issued", session_id="sess-88-004")
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/START")))
    assert result.outcome == "session_issued"
    backend.request_handoff.assert_awaited_once()


def test_dispatch_start_mixed_case() -> None:
    backend = _make_mock_backend(outcome="issued", session_id="sess-88-005")
    dispatcher = TelegramDispatcher(backend=backend)
    result = asyncio.run(dispatcher.dispatch(_make_ctx("/Start")))
    assert result.outcome == "session_issued"
    backend.request_handoff.assert_awaited_once()
