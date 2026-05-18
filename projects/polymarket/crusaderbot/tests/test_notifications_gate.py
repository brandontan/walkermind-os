"""user_settings.notifications_on enforcement on the outbound send path.

The toggle previously only wrote the DB column — nothing read it. These
tests pin the contract:
  * notifications_on=False suppresses per-user trade notifications
  * notifications_on=True (or unknown) still delivers — fail-open
  * operator alerts are NEVER gated by this flag

No live DB, no live Telegram. All external calls patched.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot import users
from projects.polymarket.crusaderbot.services.trade_notifications import (
    TradeNotifier,
)

_TG = 4242


def _patch_send():
    return patch(
        "projects.polymarket.crusaderbot.services.trade_notifications"
        ".notifier.notifications.send",
        new_callable=AsyncMock,
    )


def _patch_gate(enabled: bool):
    return patch.object(
        users, "notifications_enabled_by_telegram_id",
        new=AsyncMock(return_value=enabled),
    )


@pytest.mark.asyncio
async def test_entry_suppressed_when_user_opted_out():
    with _patch_send() as send, _patch_gate(False):
        await TradeNotifier().notify_entry(
            telegram_user_id=_TG, market_id="m1", market_question="Q?",
            side="yes", size_usdc=Decimal("10"), price=0.5,
            tp_pct=0.2, sl_pct=0.1,
        )
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_entry_delivered_when_enabled():
    with _patch_send() as send, _patch_gate(True):
        send.return_value = True
        await TradeNotifier().notify_entry(
            telegram_user_id=_TG, market_id="m1", market_question="Q?",
            side="yes", size_usdc=Decimal("10"), price=0.5,
            tp_pct=0.2, sl_pct=0.1,
        )
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_helper_fails_open_when_pool_unavailable():
    # No DB pool initialised → get_pool raises → must return True (fail-open),
    # never silence a beta user on an infra blip.
    def _boom():
        raise RuntimeError("pool not initialised")

    with patch.object(users, "get_pool", side_effect=_boom):
        assert await users.notifications_enabled_by_telegram_id(_TG) is True
        from uuid import uuid4
        assert await users.user_notifications_enabled(uuid4()) is True


@pytest.mark.asyncio
async def test_helper_returns_false_when_flag_off():
    class _Conn:
        async def fetchrow(self, *_a, **_k):
            return {"notifications_on": False}

    class _Acq:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_a):
            return None

    class _Pool:
        def acquire(self):
            return _Acq()

    with patch.object(users, "get_pool", return_value=_Pool()):
        assert await users.notifications_enabled_by_telegram_id(_TG) is False


@pytest.mark.asyncio
async def test_missing_column_defaults_enabled():
    class _Conn:
        async def fetchrow(self, *_a, **_k):
            return {"notifications_on": None}

    class _Acq:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_a):
            return None

    class _Pool:
        def acquire(self):
            return _Acq()

    with patch.object(users, "get_pool", return_value=_Pool()):
        assert await users.notifications_enabled_by_telegram_id(_TG) is True
