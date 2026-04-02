"""Tests for Telegram auto-clean (user message deletion).

Scenarios:
  AC-01  delete_user_message_later calls asyncio.sleep with correct delay
  AC-02  delete_user_message_later calls deleteMessage with correct payload
  AC-03  delete_user_message_later swallows sleep exceptions silently
  AC-04  delete_user_message_later swallows HTTP exceptions silently
  AC-05  schedule_user_message_delete creates a background task
  AC-06  default delay is 0.4 seconds
  AC-07  custom delay is respected
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from projects.polymarket.polyquantbot.telegram.utils.message_cleanup import (
    delete_user_message_later,
)
from projects.polymarket.polyquantbot.telegram.handlers.text_handler import (
    schedule_user_message_delete,
)


_TG_API = "https://api.telegram.org/botTEST"
_CHAT_ID = 12345
_MSG_ID = 99


# ══════════════════════════════════════════════════════════════════════════════
# AC-01  sleep called with correct delay
# ══════════════════════════════════════════════════════════════════════════════

class TestAC01SleepDelay:
    async def test_sleep_called_with_default_delay(self) -> None:
        mock_post = AsyncMock()
        mock_resp = AsyncMock()
        mock_session_inst = MagicMock()
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=False)
        mock_session_inst.post = mock_post
        mock_post.return_value = mock_resp

        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep, \
             patch("aiohttp.ClientSession", return_value=mock_session_inst):
            await delete_user_message_later(_TG_API, _CHAT_ID, _MSG_ID)

        mock_sleep.assert_awaited_once_with(0.4)


# ══════════════════════════════════════════════════════════════════════════════
# AC-02  deleteMessage called with correct payload
# ══════════════════════════════════════════════════════════════════════════════

class TestAC02DeleteMessagePayload:
    async def test_delete_message_correct_payload(self) -> None:
        mock_post = AsyncMock()
        mock_session_inst = MagicMock()
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=False)
        mock_session_inst.post = mock_post

        with patch("asyncio.sleep", new=AsyncMock()), \
             patch("aiohttp.ClientSession", return_value=mock_session_inst):
            await delete_user_message_later(_TG_API, _CHAT_ID, _MSG_ID)

        mock_post.assert_awaited_once_with(
            f"{_TG_API}/deleteMessage",
            json={"chat_id": _CHAT_ID, "message_id": _MSG_ID},
        )


# ══════════════════════════════════════════════════════════════════════════════
# AC-03  sleep exception silently swallowed
# ══════════════════════════════════════════════════════════════════════════════

class TestAC03SleepExceptionSwallowed:
    async def test_sleep_exception_does_not_raise(self) -> None:
        with patch("asyncio.sleep", new=AsyncMock(side_effect=RuntimeError("boom"))):
            # Must NOT raise
            await delete_user_message_later(_TG_API, _CHAT_ID, _MSG_ID)


# ══════════════════════════════════════════════════════════════════════════════
# AC-04  HTTP exception silently swallowed
# ══════════════════════════════════════════════════════════════════════════════

class TestAC04HttpExceptionSwallowed:
    async def test_http_exception_does_not_raise(self) -> None:
        mock_session_inst = MagicMock()
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=False)
        mock_session_inst.post = AsyncMock(side_effect=ConnectionError("network error"))

        with patch("asyncio.sleep", new=AsyncMock()), \
             patch("aiohttp.ClientSession", return_value=mock_session_inst):
            # Must NOT raise
            await delete_user_message_later(_TG_API, _CHAT_ID, _MSG_ID)


# ══════════════════════════════════════════════════════════════════════════════
# AC-05  schedule_user_message_delete creates a background task
# ══════════════════════════════════════════════════════════════════════════════

class TestAC05ScheduleCreatesTask:
    async def test_creates_asyncio_task(self) -> None:
        created_tasks: list = []

        original_create_task = asyncio.create_task

        def fake_create_task(coro, **kwargs):
            task = original_create_task(coro, **kwargs)
            created_tasks.append(task)
            return task

        mock_session_inst = MagicMock()
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=False)
        mock_session_inst.post = AsyncMock()

        with patch("asyncio.create_task", side_effect=fake_create_task), \
             patch("asyncio.sleep", new=AsyncMock()), \
             patch("aiohttp.ClientSession", return_value=mock_session_inst):
            await schedule_user_message_delete(_TG_API, _CHAT_ID, _MSG_ID)
            # Allow the background task to complete
            await asyncio.gather(*created_tasks, return_exceptions=True)

        assert len(created_tasks) == 1


# ══════════════════════════════════════════════════════════════════════════════
# AC-06  default delay is 0.4 seconds
# ══════════════════════════════════════════════════════════════════════════════

class TestAC06DefaultDelay:
    async def test_default_delay_is_0_4(self) -> None:
        import inspect
        sig = inspect.signature(delete_user_message_later)
        assert sig.parameters["delay"].default == 0.4


# ══════════════════════════════════════════════════════════════════════════════
# AC-07  custom delay is respected
# ══════════════════════════════════════════════════════════════════════════════

class TestAC07CustomDelay:
    async def test_custom_delay_passed_to_sleep(self) -> None:
        mock_post = AsyncMock()
        mock_session_inst = MagicMock()
        mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
        mock_session_inst.__aexit__ = AsyncMock(return_value=False)
        mock_session_inst.post = mock_post

        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep, \
             patch("aiohttp.ClientSession", return_value=mock_session_inst):
            await delete_user_message_later(_TG_API, _CHAT_ID, _MSG_ID, delay=0.3)

        mock_sleep.assert_awaited_once_with(0.3)
