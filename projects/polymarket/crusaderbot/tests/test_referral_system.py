"""Hermetic tests for Track I — Referral + Share System.

Coverage:
    referral_service
      * parse_ref_param — valid ref_ prefix returns code
      * parse_ref_param — missing prefix returns None
      * parse_ref_param — wrong length returns None
      * parse_ref_param — None start_param returns None
      * parse_ref_param — invalid chars rejected
      * build_deep_link — correct URL format
      * get_or_create_referral_code — creates code on first call
      * get_or_create_referral_code — returns existing code on second call
      * get_or_create_referral_code — retries on collision, succeeds
      * record_referral — records event and increments uses
      * record_referral — unknown code returns False
      * record_referral — self-referral returns False
      * record_referral — duplicate referral (unique constraint) returns False
      * get_referral_stats — returns correct stats with REFERRAL_PAYOUT_ENABLED=False
      * _calculate_referral_earnings — returns 0.0 when REFERRAL_PAYOUT_ENABLED=False

    config
      * REFERRAL_PAYOUT_ENABLED default is False
      * FEE_COLLECTION_ENABLED default is False

    notifier
      * notify_tp_hit — reply_markup forwarded to notifications.send
      * notify_sl_hit — sends with default My Trades/Dashboard keyboard when no reply_markup passed
      * notify_manual_close — reply_markup forwarded to notifications.send

No live DB, no live Telegram. All external calls patched.
"""
from __future__ import annotations

import asyncio
import string
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4, UUID

import pytest

from projects.polymarket.crusaderbot.services.referral.referral_service import (
    parse_ref_param,
    build_deep_link,
    _CODE_ALPHABET,
    _CODE_LENGTH,
    _BOT_USERNAME,
)

# ---------------------------------------------------------------------------
# parse_ref_param
# ---------------------------------------------------------------------------

_VALID_CODE = "ABCD1234"


def test_parse_ref_param_valid():
    assert parse_ref_param(f"ref_{_VALID_CODE}") == _VALID_CODE


def test_parse_ref_param_no_prefix():
    assert parse_ref_param(_VALID_CODE) is None


def test_parse_ref_param_none():
    assert parse_ref_param(None) is None


def test_parse_ref_param_short_code():
    assert parse_ref_param("ref_ABC") is None


def test_parse_ref_param_invalid_chars():
    assert parse_ref_param("ref_abcd1234") is None  # lowercase not in alphabet


def test_parse_ref_param_empty_string():
    assert parse_ref_param("") is None


# ---------------------------------------------------------------------------
# build_deep_link
# ---------------------------------------------------------------------------

def test_build_deep_link():
    link = build_deep_link(_VALID_CODE)
    assert link == f"https://t.me/{_BOT_USERNAME}?start=ref_{_VALID_CODE}"
    assert _VALID_CODE in link


# ---------------------------------------------------------------------------
# get_or_create_referral_code — DB patched
# ---------------------------------------------------------------------------

def _make_pool_ctx(fetchrow_return=None, execute_side_effect=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    if execute_side_effect:
        conn.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        conn.execute = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_get_or_create_referral_code_creates_new():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    user_id = uuid4()
    pool, conn = _make_pool_ctx(fetchrow_return=None)

    with patch.object(referral_service, "get_pool", return_value=pool):
        code = await referral_service.get_or_create_referral_code(user_id)

    assert len(code) == _CODE_LENGTH
    assert all(c in _CODE_ALPHABET for c in code)
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_referral_code_returns_existing():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    user_id = uuid4()
    existing_row = {"code": _VALID_CODE}
    pool, conn = _make_pool_ctx(fetchrow_return=existing_row)

    with patch.object(referral_service, "get_pool", return_value=pool):
        code = await referral_service.get_or_create_referral_code(user_id)

    assert code == _VALID_CODE
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_referral_code_retries_on_collision():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    user_id = uuid4()
    call_count = {"n": 0}

    async def _execute_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise Exception("unique constraint violation")

    pool, conn = _make_pool_ctx(
        fetchrow_return=None,
        execute_side_effect=_execute_side_effect,
    )

    with patch.object(referral_service, "get_pool", return_value=pool):
        code = await referral_service.get_or_create_referral_code(user_id)

    assert len(code) == _CODE_LENGTH
    assert call_count["n"] == 3


# ---------------------------------------------------------------------------
# record_referral — DB patched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_referral_unknown_code():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    pool, conn = _make_pool_ctx(fetchrow_return=None)

    with patch.object(referral_service, "get_pool", return_value=pool):
        result = await referral_service.record_referral(
            referrer_code=_VALID_CODE,
            referred_user_id=uuid4(),
        )

    assert result is False


@pytest.mark.asyncio
async def test_record_referral_self_referral():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    user_id = uuid4()
    referrer_row = {"id": 1, "user_id": user_id}
    pool, conn = _make_pool_ctx(fetchrow_return=referrer_row)

    with patch.object(referral_service, "get_pool", return_value=pool):
        result = await referral_service.record_referral(
            referrer_code=_VALID_CODE,
            referred_user_id=user_id,
        )

    assert result is False


@pytest.mark.asyncio
async def test_record_referral_success():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    referrer_id = uuid4()
    referred_id = uuid4()
    referrer_row = {"id": 1, "user_id": referrer_id}

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=referrer_row)
    conn.execute = AsyncMock(return_value=None)

    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(referral_service, "get_pool", return_value=pool):
        result = await referral_service.record_referral(
            referrer_code=_VALID_CODE,
            referred_user_id=referred_id,
        )

    assert result is True


@pytest.mark.asyncio
async def test_record_referral_duplicate_returns_false():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    referrer_id = uuid4()
    referred_id = uuid4()
    referrer_row = {"id": 1, "user_id": referrer_id}

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=referrer_row)
    conn.execute = AsyncMock(side_effect=Exception("unique constraint violation"))

    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(referral_service, "get_pool", return_value=pool):
        result = await referral_service.record_referral(
            referrer_code=_VALID_CODE,
            referred_user_id=referred_id,
        )

    assert result is False


# ---------------------------------------------------------------------------
# get_referral_stats — payout guard OFF
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_referral_stats_payout_disabled():
    from projects.polymarket.crusaderbot.services.referral import referral_service

    user_id = uuid4()
    stats_row = {"code": _VALID_CODE, "uses": 3, "referred_users": 3}
    pool, conn = _make_pool_ctx(fetchrow_return=stats_row)

    fake_settings = SimpleNamespace(REFERRAL_PAYOUT_ENABLED=False)

    with (
        patch.object(referral_service, "get_pool", return_value=pool),
        patch.object(referral_service, "get_settings", return_value=fake_settings),
    ):
        stats = await referral_service.get_referral_stats(user_id)

    assert stats["code"] == _VALID_CODE
    assert stats["total_referrals"] == 3
    assert stats["total_earnings"] == 0.0
    assert _VALID_CODE in stats["deep_link"]


# ---------------------------------------------------------------------------
# config — guard defaults
# ---------------------------------------------------------------------------

def test_referral_payout_enabled_default_false():
    from projects.polymarket.crusaderbot.config import Settings
    required = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "DATABASE_URL": "postgresql://x",
        "ALCHEMY_POLYGON_WS_URL": "wss://x",
        "OPERATOR_CHAT_ID": "1",
        "WALLET_HD_SEED": "seed",
        "WALLET_ENCRYPTION_KEY": "key",
        "POLYGON_RPC_URL": "https://x",
    }
    s = Settings(**required)
    assert s.REFERRAL_PAYOUT_ENABLED is False


def test_fee_collection_enabled_default_false():
    from projects.polymarket.crusaderbot.config import Settings
    required = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "DATABASE_URL": "postgresql://x",
        "ALCHEMY_POLYGON_WS_URL": "wss://x",
        "OPERATOR_CHAT_ID": "1",
        "WALLET_HD_SEED": "seed",
        "WALLET_ENCRYPTION_KEY": "key",
        "POLYGON_RPC_URL": "https://x",
    }
    s = Settings(**required)
    assert s.FEE_COLLECTION_ENABLED is False


# ---------------------------------------------------------------------------
# TradeNotifier — reply_markup forwarded
# ---------------------------------------------------------------------------

def _patch_send():
    return patch(
        "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications.send",
        new_callable=AsyncMock,
        return_value=True,
    )


@pytest.mark.asyncio
async def test_notify_tp_hit_with_reply_markup():
    from projects.polymarket.crusaderbot.services.trade_notifications import TradeNotifier
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Share", callback_data="x")]])
    notifier = TradeNotifier()

    with _patch_send() as mock_send:
        await notifier.notify_tp_hit(
            telegram_user_id=99,
            market_id="m1",
            market_question="Will X happen?",
            side="yes",
            exit_price=0.8,
            pnl_usdc=50.0,
            reply_markup=kb,
        )

    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs.get("reply_markup") is kb


@pytest.mark.asyncio
async def test_notify_sl_hit_no_reply_markup():
    from projects.polymarket.crusaderbot.services.trade_notifications import TradeNotifier
    from telegram import InlineKeyboardMarkup

    notifier = TradeNotifier()
    with _patch_send() as mock_send:
        await notifier.notify_sl_hit(
            telegram_user_id=99,
            market_id="m1",
            market_question=None,
            side="no",
            exit_price=0.2,
            pnl_usdc=-30.0,
        )

    mock_send.assert_called_once()
    assert isinstance(mock_send.call_args.kwargs.get("reply_markup"), InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_notify_manual_close_with_reply_markup():
    from projects.polymarket.crusaderbot.services.trade_notifications import TradeNotifier
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Share", callback_data="x")]])
    notifier = TradeNotifier()

    with _patch_send() as mock_send:
        await notifier.notify_manual_close(
            telegram_user_id=99,
            market_id="m1",
            market_question="Test market",
            side="yes",
            exit_price=0.9,
            pnl_usdc=100.0,
            reply_markup=kb,
        )

    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs.get("reply_markup") is kb
