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


# ── on-chain transfer path (C1: live capital exit, guarded) ───────────────────

import uuid as _uuid
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot import config as _config


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _Conn:
    """Records executed SQL; returns scripted fetchval/fetchrow values."""

    def __init__(self, fetchval=None, fetchrow=None) -> None:
        self._fetchval = fetchval
        self._fetchrow = fetchrow
        self.executed: list[tuple] = []

    async def fetchval(self, sql, *args):
        return self._fetchval

    async def fetchrow(self, sql, *args):
        return self._fetchrow

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    def transaction(self):
        return _Txn()


class _Acq:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        return None


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self):
        return _Acq(self._conn)


def _settings(execution_validated: bool):
    class _S:
        EXECUTION_PATH_VALIDATED = execution_validated
        CUSTODY_MODE = "eoa"  # default; custody dispatcher routes to polygon_usdc
    return _S()


@pytest.mark.asyncio
async def test_transfer_usdc_blocked_when_guard_off() -> None:
    """transfer_usdc refuses before any signing when the guard is false."""
    from projects.polymarket.crusaderbot.integrations import polygon_usdc

    with patch.object(polygon_usdc, "get_settings", return_value=_settings(False)):
        with pytest.raises(RuntimeError, match="EXECUTION_PATH_VALIDATED=false"):
            await polygon_usdc.transfer_usdc(
                "0xAbCd1234567890EF1234567890abcdef12345678", Decimal("10")
            )


@pytest.mark.asyncio
async def test_onchain_transfer_deferred_in_paper_mode() -> None:
    """Paper mode: no transfer, row untouched, returns None."""
    from projects.polymarket.crusaderbot.wallet import withdrawals

    conn = _Conn()
    with patch.object(_config, "get_settings", return_value=_settings(False)), \
         patch.object(withdrawals, "get_pool", return_value=_Pool(conn)):
        result = await withdrawals._attempt_onchain_transfer(
            _uuid.uuid4(), "0xAbCd1234567890EF1234567890abcdef12345678",
            Decimal("10"),
        )
    assert result is None
    assert conn.executed == []  # no status writes in paper mode


@pytest.mark.asyncio
async def test_onchain_transfer_completes_and_records_tx() -> None:
    """Live success: marks processing → completed and persists tx_hash."""
    from projects.polymarket.crusaderbot.wallet import withdrawals
    from projects.polymarket.crusaderbot.integrations import polygon_usdc
    from projects.polymarket.crusaderbot import audit

    wid = _uuid.uuid4()
    conn = _Conn(fetchval=None)  # no existing tx_hash
    fake_result = {"tx_hash": "0xdead", "gas_used": 65000, "status": 1}

    with patch.object(_config, "get_settings", return_value=_settings(True)), \
         patch.object(withdrawals, "get_pool", return_value=_Pool(conn)), \
         patch.object(polygon_usdc, "transfer_usdc",
                      AsyncMock(return_value=fake_result)) as mock_xfer, \
         patch.object(audit, "write", AsyncMock()) as mock_audit:
        result = await withdrawals._attempt_onchain_transfer(
            wid, "0xAbCd1234567890EF1234567890abcdef12345678", Decimal("10"),
        )

    assert result["tx_hash"] == "0xdead"
    mock_xfer.assert_awaited_once()
    sql_text = " ".join(sql for sql, _ in conn.executed)
    assert "'processing'" in sql_text
    assert "'completed'" in sql_text
    assert any("0xdead" in str(args) for _, args in conn.executed)
    mock_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_onchain_transfer_idempotent_when_tx_exists() -> None:
    """A row that already has a tx_hash is never re-sent."""
    from projects.polymarket.crusaderbot.wallet import withdrawals
    from projects.polymarket.crusaderbot.integrations import polygon_usdc

    conn = _Conn(fetchval="0xexisting")
    with patch.object(_config, "get_settings", return_value=_settings(True)), \
         patch.object(withdrawals, "get_pool", return_value=_Pool(conn)), \
         patch.object(polygon_usdc, "transfer_usdc", AsyncMock()) as mock_xfer:
        result = await withdrawals._attempt_onchain_transfer(
            _uuid.uuid4(), "0xAbCd1234567890EF1234567890abcdef12345678",
            Decimal("10"),
        )
    assert result["skipped"] is True
    mock_xfer.assert_not_awaited()
    assert conn.executed == []  # never marked processing


@pytest.mark.asyncio
async def test_approve_marks_failed_on_transfer_error() -> None:
    """A transfer failure flips the row to 'failed' with the error recorded."""
    from projects.polymarket.crusaderbot.wallet import withdrawals

    wid = _uuid.uuid4()
    approved_row = {
        "id": wid,
        "destination_address": "0xAbCd1234567890EF1234567890abcdef12345678",
        "amount_usdc": Decimal("10"),
        "status": "approved",
    }
    conn = _Conn(fetchrow=approved_row)

    async def _boom(*_a, **_k):
        raise RuntimeError("hot-pool USDC 0 < requested 10")

    with patch.object(withdrawals, "get_pool", return_value=_Pool(conn)), \
         patch.object(withdrawals, "_attempt_onchain_transfer", _boom):
        await withdrawals.approve_withdrawal(wid)

    sql_text = " ".join(sql for sql, _ in conn.executed)
    assert "'failed'" in sql_text
    assert any("hot-pool USDC" in str(args) for _, args in conn.executed)


@pytest.mark.asyncio
async def test_preflight_failure_refunds_ledger() -> None:
    """A pre-broadcast failure marks 'failed' AND refunds the debit."""
    from projects.polymarket.crusaderbot.wallet import withdrawals
    from projects.polymarket.crusaderbot.wallet import ledger
    from projects.polymarket.crusaderbot.integrations.polygon_usdc import PreflightError

    wid = _uuid.uuid4()
    uid = _uuid.uuid4()
    conn = _Conn(fetchrow={"user_id": uid})  # row matched by the failed-update

    async def _preflight_boom(*_a, **_k):
        raise PreflightError("EXECUTION_PATH_VALIDATED=false")

    with patch.object(withdrawals, "get_pool", return_value=_Pool(conn)), \
         patch.object(withdrawals, "_attempt_onchain_transfer", _preflight_boom), \
         patch.object(ledger, "credit_in_conn", AsyncMock()) as mock_credit:
        await withdrawals._settle_withdrawal(
            wid, "0xAbCd1234567890EF1234567890abcdef12345678", Decimal("10"),
        )

    mock_credit.assert_awaited_once()  # ledger refunded — no capital moved


@pytest.mark.asyncio
async def test_post_broadcast_failure_does_not_refund() -> None:
    """An ambiguous post-broadcast failure marks 'failed' but never refunds."""
    from projects.polymarket.crusaderbot.wallet import withdrawals
    from projects.polymarket.crusaderbot.wallet import ledger

    conn = _Conn()

    async def _boom(*_a, **_k):
        raise RuntimeError("receipt timeout")

    with patch.object(withdrawals, "get_pool", return_value=_Pool(conn)), \
         patch.object(withdrawals, "_attempt_onchain_transfer", _boom), \
         patch.object(ledger, "credit_in_conn", AsyncMock()) as mock_credit:
        await withdrawals._settle_withdrawal(
            _uuid.uuid4(), "0xAbCd1234567890EF1234567890abcdef12345678",
            Decimal("10"),
        )

    mock_credit.assert_not_awaited()
    assert any("'failed'" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_auto_mode_fires_settlement_at_request_time() -> None:
    """Auto-approval mode settles on-chain at request time (not via approve)."""
    from projects.polymarket.crusaderbot.wallet import withdrawals

    uid = _uuid.uuid4()
    row = {"id": _uuid.uuid4(), "user_id": uid, "status": "approved"}
    conn = _Conn(fetchrow=row)

    with patch.object(withdrawals, "get_approval_mode",
                      AsyncMock(return_value="auto")), \
         patch.object(withdrawals, "get_pool", return_value=_Pool(conn)), \
         patch.object(withdrawals, "debit_in_conn", AsyncMock()), \
         patch.object(withdrawals, "_settle_withdrawal", AsyncMock()) as mock_settle:
        await withdrawals.create_withdrawal_request(
            uid, Decimal("10"), "0xAbCd1234567890EF1234567890abcdef12345678",
        )

    mock_settle.assert_awaited_once()
