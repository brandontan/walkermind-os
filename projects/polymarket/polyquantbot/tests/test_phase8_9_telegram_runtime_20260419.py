"""Phase 8.9 — Telegram Runtime Loop Foundation tests.

Covers:
- extract_command_context: command detection, staging contract, edge cases
- TelegramPollingLoop: inbound dispatch, reply routing, malformed/non-command
  safe handling, offset advancement, exception resilience
- TelegramRuntimeAdapter: abstract boundary enforced (MockTelegramAdapter)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from projects.polymarket.polyquantbot.client.telegram.dispatcher import (
    DispatchResult,
    TelegramCommandContext,
    TelegramDispatcher,
)
from projects.polymarket.polyquantbot.client.telegram.runtime import (
    TelegramInboundUpdate,
    TelegramPollingLoop,
    TelegramRuntimeAdapter,
    extract_command_context,
)


# ---------------------------------------------------------------------------
# MockTelegramAdapter — in-memory adapter for tests
# ---------------------------------------------------------------------------


class MockTelegramAdapter(TelegramRuntimeAdapter):
    def __init__(self, updates: list[TelegramInboundUpdate]) -> None:
        self._updates = updates
        self.replies: list[tuple[str, str]] = []

    async def get_updates(self, offset: int = 0, limit: int = 100) -> list[TelegramInboundUpdate]:
        return [u for u in self._updates if u.update_id >= offset]

    async def send_reply(self, chat_id: str, text: str) -> None:
        self.replies.append((chat_id, text))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_update(
    update_id: int = 1,
    chat_id: str = "chat1",
    from_user_id: str = "tg123",
    text: str = "/start",
) -> TelegramInboundUpdate:
    return TelegramInboundUpdate(
        update_id=update_id,
        chat_id=chat_id,
        from_user_id=from_user_id,
        text=text,
    )


def _mock_dispatcher(
    outcome: str = "session_issued",
    reply_text: str = "Welcome!",
) -> TelegramDispatcher:
    backend = MagicMock()
    dispatcher = TelegramDispatcher(backend=backend)
    dispatcher.dispatch = AsyncMock(
        return_value=DispatchResult(
            outcome=outcome,
            reply_text=reply_text,
            session_id="sess-9-test",
        )
    )
    return dispatcher


# ---------------------------------------------------------------------------
# extract_command_context — command detection
# ---------------------------------------------------------------------------


def test_extract_command_context_start() -> None:
    update = _make_update(text="/start")
    ctx = extract_command_context(update, tenant_id="t1", user_id="u1")
    assert ctx is not None
    assert ctx.command == "/start"
    assert ctx.from_user_id == "tg123"
    assert ctx.chat_id == "chat1"
    assert ctx.tenant_id == "t1"
    assert ctx.user_id == "u1"


def test_extract_command_context_non_command() -> None:
    update = _make_update(text="hello world")
    assert extract_command_context(update) is None


def test_extract_command_context_empty_text() -> None:
    update = _make_update(text="")
    assert extract_command_context(update) is None


def test_extract_command_context_whitespace_text() -> None:
    update = _make_update(text="   ")
    assert extract_command_context(update) is None


def test_extract_command_context_unknown_command() -> None:
    update = _make_update(text="/help")
    ctx = extract_command_context(update)
    assert ctx is not None
    assert ctx.command == "/help"


def test_extract_command_context_command_with_args() -> None:
    update = _make_update(text="/start extra args")
    ctx = extract_command_context(update)
    assert ctx is not None
    assert ctx.command == "/start"


def test_extract_command_context_staging_defaults() -> None:
    update = _make_update(text="/start")
    ctx = extract_command_context(update)
    assert ctx is not None
    assert ctx.tenant_id == "staging"
    assert ctx.user_id == "staging"


# ---------------------------------------------------------------------------
# TelegramPollingLoop — inbound /start → dispatch → reply
# ---------------------------------------------------------------------------


def test_polling_loop_run_once_dispatches_start() -> None:
    update = _make_update(update_id=10, chat_id="c1", from_user_id="tg1", text="/start")
    adapter = MockTelegramAdapter([update])
    dispatcher = _mock_dispatcher()
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    count = asyncio.run(loop.run_once())
    assert count == 1
    dispatcher.dispatch.assert_called_once()
    dispatched_ctx: TelegramCommandContext = dispatcher.dispatch.call_args[0][0]
    assert dispatched_ctx.command == "/start"
    assert dispatched_ctx.from_user_id == "tg1"
    assert dispatched_ctx.chat_id == "c1"


def test_polling_loop_run_once_sends_reply() -> None:
    update = _make_update(update_id=11, chat_id="c1", from_user_id="tg1", text="/start")
    adapter = MockTelegramAdapter([update])
    dispatcher = _mock_dispatcher(reply_text="Welcome to CrusaderBot!")
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    asyncio.run(loop.run_once())
    assert len(adapter.replies) == 1
    assert adapter.replies[0][0] == "c1"
    assert adapter.replies[0][1] == "Welcome to CrusaderBot!"


def test_polling_loop_run_once_help_command_reply() -> None:
    """Help command routes through real TelegramDispatcher and returns command list reply."""
    update = _make_update(update_id=12, chat_id="c2", from_user_id="tg2", text="/help")
    adapter = MockTelegramAdapter([update])
    backend = MagicMock()
    dispatcher = TelegramDispatcher(backend=backend)
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    asyncio.run(loop.run_once())
    assert len(adapter.replies) == 1
    assert "CrusaderBot Help" in adapter.replies[0][1]


def test_polling_loop_run_once_non_command_no_dispatch() -> None:
    """Non-command text messages are skipped — no dispatch, no reply."""
    update = _make_update(update_id=13, chat_id="c3", from_user_id="tg3", text="hello there")
    adapter = MockTelegramAdapter([update])
    dispatcher = _mock_dispatcher()
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    asyncio.run(loop.run_once())
    dispatcher.dispatch.assert_not_called()
    assert len(adapter.replies) == 0


def test_polling_loop_run_once_dispatch_exception_sends_error_reply() -> None:
    """Dispatch exception is caught; safe error reply is sent; loop does not crash."""
    update = _make_update(update_id=14, chat_id="c4", from_user_id="tg4", text="/start")
    adapter = MockTelegramAdapter([update])
    backend = MagicMock()
    dispatcher = TelegramDispatcher(backend=backend)
    dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("backend unavailable"))
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    asyncio.run(loop.run_once())
    assert len(adapter.replies) == 1
    assert "error" in adapter.replies[0][1].lower()


def test_polling_loop_run_once_advances_offset() -> None:
    """Offset advances past the last processed update_id after run_once."""
    updates = [
        _make_update(update_id=20, text="/start"),
        _make_update(update_id=21, text="/start"),
    ]
    adapter = MockTelegramAdapter(updates)
    dispatcher = _mock_dispatcher()
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    asyncio.run(loop.run_once())
    assert loop._offset == 22


def test_polling_loop_run_once_empty_updates() -> None:
    adapter = MockTelegramAdapter([])
    dispatcher = _mock_dispatcher()
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    count = asyncio.run(loop.run_once())
    assert count == 0


def test_polling_loop_run_once_send_reply_exception_no_crash() -> None:
    """send_reply exception is caught and logged — loop does not crash."""
    update = _make_update(update_id=30, text="/start")
    adapter = MockTelegramAdapter([update])
    adapter.send_reply = AsyncMock(side_effect=RuntimeError("network error"))
    dispatcher = _mock_dispatcher()
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    count = asyncio.run(loop.run_once())
    assert count == 1


def test_polling_loop_run_once_multiple_mixed_updates() -> None:
    """Mixed update batch: /start dispatched, non-command skipped, /help dispatched."""
    updates = [
        _make_update(update_id=40, chat_id="c1", from_user_id="u1", text="/start"),
        _make_update(update_id=41, chat_id="c2", from_user_id="u2", text="not a command"),
        _make_update(update_id=42, chat_id="c3", from_user_id="u3", text="/help"),
    ]
    adapter = MockTelegramAdapter(updates)
    dispatcher = _mock_dispatcher()
    loop = TelegramPollingLoop(adapter=adapter, dispatcher=dispatcher)
    count = asyncio.run(loop.run_once())
    assert count == 3
    assert dispatcher.dispatch.call_count == 2
    assert len(adapter.replies) == 2
    assert loop._offset == 43


def test_polling_loop_uses_staging_contract() -> None:
    """Context extracted with configured staging_tenant_id and staging_user_id."""
    update = _make_update(update_id=50, text="/start")
    adapter = MockTelegramAdapter([update])
    dispatcher = _mock_dispatcher()
    loop = TelegramPollingLoop(
        adapter=adapter,
        dispatcher=dispatcher,
        staging_tenant_id="t-stage",
        staging_user_id="u-stage",
    )
    asyncio.run(loop.run_once())
    dispatched_ctx: TelegramCommandContext = dispatcher.dispatch.call_args[0][0]
    assert dispatched_ctx.tenant_id == "t-stage"
    assert dispatched_ctx.user_id == "u-stage"
