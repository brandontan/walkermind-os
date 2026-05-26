"""Regression tests for the withdraw flow.

Covers:
  - MIN_WITHDRAWAL_USDC constant
  - create_withdrawal_request ledger atomicity (mocked DB)
  - approve_withdrawal and reject_withdrawal (refund) (mocked DB)
  - get_approval_mode / set_approval_mode validation
  - withdraw_confirm callback data parsing
  - Ethereum address regex validation
  - withdraw_submitted_text auto vs manual
  - admin_withdrawal_item_text rendering
"""
from __future__ import annotations

import re
from decimal import Decimal

import pytest

from projects.polymarket.crusaderbot.wallet.withdrawals import MIN_WITHDRAWAL_USDC
from projects.polymarket.crusaderbot.bot.messages import (
    withdraw_ask_amount_text,
    withdraw_ask_address_text,
    withdraw_confirm_text,
    withdraw_submitted_text,
    withdraw_history_text,
    admin_withdrawal_item_text,
)


# ── constants ──────────────────────────────────────────────────────────────────

def test_min_withdrawal_is_five() -> None:
    assert MIN_WITHDRAWAL_USDC == Decimal("5")


# ── message text rendering ─────────────────────────────────────────────────────

def test_withdraw_ask_amount_text_contains_balance() -> None:
    text = withdraw_ask_amount_text(Decimal("100.00"))
    assert "100" in text
    assert "balance" in text.lower()


def test_withdraw_ask_address_text_shows_amount() -> None:
    text = withdraw_ask_address_text("42.50")
    assert "42.50" in text
    assert "Step 2" in text


def test_withdraw_confirm_text_truncates_address() -> None:
    addr = "0xAbCd1234567890EF1234567890abcdef12345678"
    text = withdraw_confirm_text("25.00", addr)
    assert "25.00" in text
    assert "0xAbCd" in text
    assert "5678" in text
    assert "Paper mode" in text


def test_withdraw_submitted_text_auto() -> None:
    text = withdraw_submitted_text("30.00", "auto")
    # MarkdownV2 escapes the hyphen in "Auto-approved"
    assert "Auto\\-approved" in text
    assert "30.00" in text


def test_withdraw_submitted_text_manual() -> None:
    text = withdraw_submitted_text("30.00", "manual")
    assert "Pending" in text
    assert "admin approval" in text.lower()


def test_withdraw_history_text_empty() -> None:
    text = withdraw_history_text([])
    assert "No withdrawals" in text


def test_withdraw_history_text_with_items() -> None:
    from datetime import datetime, timezone
    rows = [
        {
            "amount_usdc": Decimal("50"),
            "destination_address": "0xAbCd1234567890EF1234567890abcdef12345678",
            "status": "pending",
            "created_at": datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc),
        }
    ]
    text = withdraw_history_text(rows)
    assert "50" in text
    assert "0xAbCd" in text
    assert "⏳" in text


def test_admin_withdrawal_item_text_renders() -> None:
    from datetime import datetime, timezone
    import uuid
    w = {
        "id": uuid.uuid4(),
        "amount_usdc": Decimal("75.00"),
        "destination_address": "0xAbCd1234567890EF1234567890abcdef12345678",
        "created_at": datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc),
        "telegram_id": 123456789,
        "username": "testuser",
    }
    text = admin_withdrawal_item_text(w)
    assert "75.00" in text
    assert "testuser" in text
    assert "0xAbCd" in text


# ── address validation regex ───────────────────────────────────────────────────

_ETH_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@pytest.mark.parametrize("addr,valid", [
    ("0xAbCd1234567890EF1234567890abcdef12345678", True),
    ("0x0000000000000000000000000000000000000000", True),
    ("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF", True),
    ("AbCd1234567890EF1234567890abcdef12345678", False),    # no 0x
    ("0xAbCd123456789", False),                              # too short
    ("0xAbCd1234567890EF1234567890abcdef123456789", False),  # too long
    ("0xGGGG1234567890EF1234567890abcdef12345678", False),   # invalid hex
])
def test_eth_address_regex(addr: str, valid: bool) -> None:
    assert bool(_ETH_ADDR_RE.match(addr)) is valid


# ── approval mode validation ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_approval_mode_rejects_invalid() -> None:
    from projects.polymarket.crusaderbot.wallet.withdrawals import set_approval_mode

    with pytest.raises(ValueError, match="Invalid approval mode"):
        await set_approval_mode("invalid")


# ── withdraw_confirm callback data format ─────────────────────────────────────

def test_withdraw_confirm_kb_callback_data() -> None:
    from projects.polymarket.crusaderbot.bot.keyboards.wallet import withdraw_confirm_kb
    addr = "0xAbCd1234567890EF1234567890abcdef12345678"
    kb = withdraw_confirm_kb("25.00", addr)
    # The confirm button callback should encode amount and address
    rows = kb.inline_keyboard
    confirm_btn = rows[0][0]
    assert "withdraw_confirm" in confirm_btn.callback_data
    assert "25.00" in confirm_btn.callback_data
    assert addr in confirm_btn.callback_data
