"""Priority 7 — Settlement Telegram Wiring — Tests (Gate 1c).

Test IDs: ST-48 .. ST-55

Coverage:
  ST-48  /settlement_status guarded from non-operator chat
  ST-49  /settlement_status calls correct backend endpoint and formats reply
  ST-50  /settlement_status returns usage hint when no workflow_id given
  ST-51  /retry_status calls correct backend endpoint and formats reply
  ST-52  /failed_batches returns empty-list acknowledgement
  ST-53  /settlement_intervene returns usage hint when args missing
  ST-54  /settlement_intervene calls backend and formats result
  ST-55  backend error is surfaced cleanly (no exception propagation)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from projects.polymarket.polyquantbot.client.telegram.dispatcher import (
    DispatchResult,
    TelegramCommandContext,
    TelegramDispatcher,
)

_OPERATOR_CHAT = "op_chat_001"


def _ctx(
    command: str,
    argument: str = "",
    chat_id: str = _OPERATOR_CHAT,
    from_user_id: str = "tg_admin",
) -> TelegramCommandContext:
    return TelegramCommandContext(
        command=command,
        from_user_id=from_user_id,
        chat_id=chat_id,
        tenant_id="t1",
        user_id="u1",
        argument=argument,
    )


def _dispatcher(backend: object) -> TelegramDispatcher:
    return TelegramDispatcher(backend=backend, operator_chat_id=_OPERATOR_CHAT)  # type: ignore[arg-type]


# ── ST-48: guard — non-operator chat blocked ───────────────────────────────

@pytest.mark.asyncio
async def test_st48_settlement_status_guarded_from_public_chat() -> None:
    backend = MagicMock()
    d = _dispatcher(backend)
    result = await d.dispatch(_ctx("/settlement_status", argument="wf_001", chat_id="public_chat"))
    assert result.outcome == "unknown_command"


# ── ST-49: /settlement_status formats reply ────────────────────────────────

@pytest.mark.asyncio
async def test_st49_settlement_status_formats_reply() -> None:
    backend = MagicMock()
    backend.settlement_get = AsyncMock(
        return_value={
            "ok": True,
            "data": {
                "workflow_id": "wf_001",
                "status": "COMPLETED",
                "retry_attempt_count": 1,
                "amount": 50.0,
                "currency": "USD",
                "mode": "paper",
                "last_blocked_reason": None,
                "wallet_id": "wallet_abc",
            },
        }
    )
    d = _dispatcher(backend)
    result = await d.dispatch(_ctx("/settlement_status", argument="wf_001"))
    assert result.outcome == "ok"
    assert "wf_001" in result.reply_text
    assert "COMPLETED" in result.reply_text
    assert "wallet_abc" in result.reply_text
    backend.settlement_get.assert_called_once_with("/admin/settlement/status/wf_001")


# ── ST-50: /settlement_status usage hint ──────────────────────────────────

@pytest.mark.asyncio
async def test_st50_settlement_status_usage_hint() -> None:
    backend = MagicMock()
    d = _dispatcher(backend)
    result = await d.dispatch(_ctx("/settlement_status", argument=""))
    assert result.outcome == "ok"
    assert "Usage" in result.reply_text


# ── ST-51: /retry_status formats reply ────────────────────────────────────

@pytest.mark.asyncio
async def test_st51_retry_status_formats_reply() -> None:
    backend = MagicMock()
    backend.settlement_get = AsyncMock(
        return_value={
            "ok": True,
            "data": {
                "workflow_id": "wf_002",
                "current_attempt": 3,
                "is_exhausted": False,
                "last_outcome": "timeout",
                "next_retry_at": "2026-04-29T00:00:00Z",
            },
        }
    )
    d = _dispatcher(backend)
    result = await d.dispatch(_ctx("/retry_status", argument="wf_002"))
    assert result.outcome == "ok"
    assert "wf_002" in result.reply_text
    assert "3" in result.reply_text
    assert "timeout" in result.reply_text
    backend.settlement_get.assert_called_once_with("/admin/settlement/retry/wf_002")


# ── ST-52: /failed_batches empty-list acknowledgement ─────────────────────

@pytest.mark.asyncio
async def test_st52_failed_batches_empty_list_acknowledged() -> None:
    backend = MagicMock()
    backend.settlement_get = AsyncMock(return_value={"ok": True, "data": []})
    d = _dispatcher(backend)
    result = await d.dispatch(_ctx("/failed_batches"))
    assert result.outcome == "ok"
    assert "none" in result.reply_text.lower()
    assert "batch result persistence" in result.reply_text
    backend.settlement_get.assert_called_once_with("/admin/settlement/failed-batches")


# ── ST-53: /settlement_intervene usage hint ───────────────────────────────

@pytest.mark.asyncio
async def test_st53_settlement_intervene_usage_hint() -> None:
    backend = MagicMock()
    d = _dispatcher(backend)
    result = await d.dispatch(_ctx("/settlement_intervene", argument="only_one_arg"))
    assert result.outcome == "ok"
    assert "Usage" in result.reply_text


# ── ST-54: /settlement_intervene calls backend and formats result ──────────

@pytest.mark.asyncio
async def test_st54_settlement_intervene_formats_result() -> None:
    backend = MagicMock()
    backend.settlement_post = AsyncMock(
        return_value={
            "ok": True,
            "data": {
                "workflow_id": "wf_003",
                "action": "force_complete",
                "success": True,
                "new_status": "COMPLETED",
            },
        }
    )
    d = _dispatcher(backend)
    result = await d.dispatch(
        _ctx("/settlement_intervene", argument="wf_003 force_complete operator review passed")
    )
    assert result.outcome == "ok"
    assert "wf_003" in result.reply_text
    assert "force_complete" in result.reply_text
    assert "COMPLETED" in result.reply_text
    backend.settlement_post.assert_called_once_with(
        "/admin/settlement/intervene",
        {
            "workflow_id": "wf_003",
            "action": "force_complete",
            "admin_user_id": "tg_admin",
            "reason": "operator review passed",
        },
    )


# ── ST-55: backend error surfaced cleanly ─────────────────────────────────

@pytest.mark.asyncio
async def test_st55_backend_error_surfaced_cleanly() -> None:
    backend = MagicMock()
    backend.settlement_get = AsyncMock(return_value={"ok": False, "detail": "http_503"})
    d = _dispatcher(backend)
    result = await d.dispatch(_ctx("/settlement_status", argument="wf_error"))
    assert result.outcome == "ok"
    assert "unavailable" in result.reply_text
    assert "http_503" in result.reply_text
