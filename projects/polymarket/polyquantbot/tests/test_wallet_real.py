"""test_wallet_real.py — Tests for core/wallet and core/security modules.

Scenarios:
  WR-01  encrypt_private_key produces Base64 output (not plaintext)
  WR-02  decrypt_private_key round-trips correctly
  WR-03  Two encryptions of same key produce different ciphertexts (fresh nonce)
  WR-04  encrypt_private_key raises ValueError for non-64-char input
  WR-05  encrypt_private_key raises EnvironmentError when WALLET_SECRET_KEY unset
  WR-06  decrypt_private_key raises ValueError on tampered ciphertext
  WR-07  WalletModel repr omits encrypted_private_key
  WR-08  WalletModel.public_dict has no encrypted_private_key
  WR-09  WalletService.create_wallet is idempotent (same address on second call)
  WR-10  WalletService.create_wallet multi-user creates isolated wallets
  WR-11  WalletService.get_wallet returns None for unknown user
  WR-12  WalletService.get_balance returns 0.0 when no wallet
  WR-13  WalletService.get_balance returns 0.0 on HTTP error (no session)
  WR-14  WalletService.withdraw raises ValueError for bad to_address
  WR-15  WalletService.withdraw raises ValueError for non-positive amount
  WR-16  WalletService.withdraw raises RuntimeError when no wallet
  WR-17  WalletService.withdraw raises RuntimeError on insufficient balance
  WR-18  handle_wallet returns (str, list) — no service injected (stub mode)
  WR-19  handle_wallet with service injected returns address in screen text
  WR-20  handle_wallet_withdraw returns withdraw screen
  WR-21  wallet_screen with address and balance renders correctly
  WR-22  wallet_balance_screen with balance renders correctly
  WR-23  wallet_withdraw_screen with address and balance renders correctly
  WR-24  wallet_withdraw_result_screen broadcast renders tx_hash
  WR-25  wallet_withdraw_result_screen pending renders note
  WR-26  build_wallet_menu contains withdraw button
  WR-27  callback_router dispatches wallet_withdraw action
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Encryption tests ───────────────────────────────────────────────────────────

_VALID_KEY = "a" * 64   # 64-char hex-valid string


@pytest.fixture(autouse=True)
def set_wallet_secret(monkeypatch):
    """Ensure WALLET_SECRET_KEY is set for all tests in this module."""
    monkeypatch.setenv("WALLET_SECRET_KEY", "test-super-secret-key-for-unit-tests-32chars!!")


def test_wr01_encrypt_not_plaintext():
    """WR-01: Encrypted output is Base64, not the plaintext hex key."""
    from projects.polymarket.polyquantbot.core.security.encryption import encrypt_private_key
    ct = encrypt_private_key(_VALID_KEY)
    assert ct != _VALID_KEY
    assert len(ct) > 10
    # Must be valid Base64 (no exception)
    import base64
    base64.b64decode(ct)


def test_wr02_encrypt_decrypt_roundtrip():
    """WR-02: decrypt(encrypt(key)) == key."""
    from projects.polymarket.polyquantbot.core.security.encryption import (
        encrypt_private_key,
        decrypt_private_key,
    )
    ct = encrypt_private_key(_VALID_KEY)
    recovered = decrypt_private_key(ct)
    assert recovered == _VALID_KEY


def test_wr03_different_ciphertexts_per_call():
    """WR-03: Two encryptions of the same key yield different ciphertexts."""
    from projects.polymarket.polyquantbot.core.security.encryption import encrypt_private_key
    ct1 = encrypt_private_key(_VALID_KEY)
    ct2 = encrypt_private_key(_VALID_KEY)
    assert ct1 != ct2


def test_wr04_encrypt_invalid_length():
    """WR-04: Encrypt raises ValueError for non-64-char input."""
    from projects.polymarket.polyquantbot.core.security.encryption import encrypt_private_key
    with pytest.raises(ValueError):
        encrypt_private_key("short_key")


def test_wr05_encrypt_missing_env(monkeypatch):
    """WR-05: Encrypt raises EnvironmentError when WALLET_SECRET_KEY is unset."""
    from projects.polymarket.polyquantbot.core.security.encryption import encrypt_private_key
    monkeypatch.delenv("WALLET_SECRET_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        encrypt_private_key(_VALID_KEY)


def test_wr06_decrypt_tampered_ciphertext():
    """WR-06: Tampered ciphertext raises ValueError on decrypt."""
    from projects.polymarket.polyquantbot.core.security.encryption import (
        encrypt_private_key,
        decrypt_private_key,
    )
    ct = encrypt_private_key(_VALID_KEY)
    # Flip the last character
    tampered = ct[:-1] + ("A" if ct[-1] != "A" else "B")
    with pytest.raises(ValueError):
        decrypt_private_key(tampered)


# ── WalletModel tests ──────────────────────────────────────────────────────────


def test_wr07_wallet_model_repr_safe():
    """WR-07: WalletModel repr does not expose encrypted_private_key."""
    from projects.polymarket.polyquantbot.core.wallet.models import WalletModel
    w = WalletModel(user_id=1, address="0xabc", encrypted_private_key="secret_blob")
    r = repr(w)
    assert "secret_blob" not in r
    assert "encrypted_private_key" not in r


def test_wr08_wallet_model_public_dict_no_key():
    """WR-08: public_dict has no encrypted_private_key."""
    from projects.polymarket.polyquantbot.core.wallet.models import WalletModel
    w = WalletModel(user_id=1, address="0xabc", encrypted_private_key="secret_blob")
    d = w.public_dict()
    assert "encrypted_private_key" not in d
    assert d["user_id"] == 1
    assert d["address"] == "0xabc"


# ── WalletService tests ────────────────────────────────────────────────────────


@pytest.fixture
def svc():
    from projects.polymarket.polyquantbot.core.wallet.service import WalletService
    return WalletService(http_session_factory=None)


async def test_wr09_create_wallet_idempotent(svc):
    """WR-09: create_wallet returns same wallet on second call."""
    w1 = await svc.create_wallet(user_id=100)
    w2 = await svc.create_wallet(user_id=100)
    assert w1.address == w2.address
    assert w1.user_id == w2.user_id


async def test_wr10_create_wallet_multi_user_isolated(svc):
    """WR-10: Different users get different wallets."""
    w1 = await svc.create_wallet(user_id=101)
    w2 = await svc.create_wallet(user_id=102)
    assert w1.address != w2.address
    assert w1.encrypted_private_key != w2.encrypted_private_key


async def test_wr11_get_wallet_unknown_user(svc):
    """WR-11: get_wallet returns None for unknown user."""
    result = await svc.get_wallet(user_id=9999)
    assert result is None


async def test_wr12_get_balance_no_wallet(svc):
    """WR-12: get_balance returns 0.0 when user has no wallet."""
    balance = await svc.get_balance(user_id=9999)
    assert balance == 0.0


async def test_wr13_get_balance_no_session(svc):
    """WR-13: get_balance returns 0.0 when http_session_factory is None."""
    await svc.create_wallet(user_id=200)
    balance = await svc.get_balance(user_id=200)
    assert balance == 0.0


async def test_wr14_withdraw_bad_address(svc):
    """WR-14: withdraw raises ValueError for invalid to_address."""
    await svc.create_wallet(user_id=300)
    with pytest.raises(ValueError, match="Invalid destination"):
        await svc.withdraw(user_id=300, to_address="bad", amount_usdc=1.0)


async def test_wr15_withdraw_non_positive_amount(svc):
    """WR-15: withdraw raises ValueError for amount <= 0."""
    await svc.create_wallet(user_id=301)
    with pytest.raises(ValueError, match="positive"):
        await svc.withdraw(
            user_id=301,
            to_address="0x" + "a" * 40,
            amount_usdc=0.0,
        )


async def test_wr16_withdraw_no_wallet(svc):
    """WR-16: withdraw raises RuntimeError when user has no wallet."""
    with pytest.raises(RuntimeError, match="No wallet found"):
        await svc.withdraw(
            user_id=9999,
            to_address="0x" + "a" * 40,
            amount_usdc=1.0,
        )


async def test_wr17_withdraw_insufficient_balance(svc):
    """WR-17: withdraw raises RuntimeError on insufficient balance."""
    await svc.create_wallet(user_id=302)
    # Balance is 0.0 (no HTTP session), request 10.0
    with pytest.raises(RuntimeError, match="Insufficient balance"):
        await svc.withdraw(
            user_id=302,
            to_address="0x" + "a" * 40,
            amount_usdc=10.0,
        )


# ── Telegram handler tests ─────────────────────────────────────────────────────


async def test_wr18_handle_wallet_no_service():
    """WR-18: handle_wallet returns (str, list) stub when service not injected."""
    import projects.polymarket.polyquantbot.telegram.handlers.wallet as wh
    # Temporarily clear service
    original = wh._wallet_service
    wh._wallet_service = None
    try:
        text, kb = await wh.handle_wallet(mode="PAPER", user_id=None)
        assert isinstance(text, str)
        assert isinstance(kb, list)
    finally:
        wh._wallet_service = original


async def test_wr19_handle_wallet_with_service():
    """WR-19: handle_wallet with service returns address in screen text."""
    import projects.polymarket.polyquantbot.telegram.handlers.wallet as wh
    from projects.polymarket.polyquantbot.core.wallet.service import WalletService

    svc = WalletService(http_session_factory=None)
    wh.set_wallet_service(svc)
    try:
        text, kb = await wh.handle_wallet(mode="PAPER", user_id=500)
        assert isinstance(text, str)
        # Address starts with 0x
        assert "0x" in text
        assert isinstance(kb, list)
    finally:
        wh._wallet_service = None


async def test_wr20_handle_wallet_withdraw():
    """WR-20: handle_wallet_withdraw returns withdraw screen."""
    import projects.polymarket.polyquantbot.telegram.handlers.wallet as wh
    wh._wallet_service = None
    text, kb = await wh.handle_wallet_withdraw(user_id=None)
    assert isinstance(text, str)
    assert "WITHDRAW" in text
    assert isinstance(kb, list)


# ── Screen template tests ──────────────────────────────────────────────────────


def test_wr21_wallet_screen_with_data():
    """WR-21: wallet_screen with address and balance renders correctly."""
    from projects.polymarket.polyquantbot.telegram.ui.screens import wallet_screen
    text = wallet_screen(mode="PAPER", address="0xabc123", balance=42.5)
    assert "0xabc123" in text
    assert "42.5000" in text
    assert "PAPER" in text


def test_wr22_wallet_balance_screen_with_balance():
    """WR-22: wallet_balance_screen with balance renders correctly."""
    from projects.polymarket.polyquantbot.telegram.ui.screens import wallet_balance_screen
    text = wallet_balance_screen(balance=10.0, address="0xtest")
    assert "10.0000" in text
    assert "0xtest" in text


def test_wr23_wallet_withdraw_screen():
    """WR-23: wallet_withdraw_screen renders address and balance."""
    from projects.polymarket.polyquantbot.telegram.ui.screens import wallet_withdraw_screen
    text = wallet_withdraw_screen(address="0xdead", balance=5.25)
    assert "0xdead" in text
    assert "5.2500" in text
    assert "WITHDRAW" in text


def test_wr24_wallet_withdraw_result_broadcast():
    """WR-24: wallet_withdraw_result_screen broadcast renders tx_hash."""
    from projects.polymarket.polyquantbot.telegram.ui.screens import wallet_withdraw_result_screen
    result = {
        "status": "broadcast",
        "to_address": "0xdest",
        "amount_usdc": 3.0,
        "tx_hash": "0xdeadbeef",
    }
    text = wallet_withdraw_result_screen(result)
    assert "0xdeadbeef" in text
    assert "SUBMITTED" in text


def test_wr25_wallet_withdraw_result_pending():
    """WR-25: wallet_withdraw_result_screen pending renders note."""
    from projects.polymarket.polyquantbot.telegram.ui.screens import wallet_withdraw_result_screen
    result = {
        "status": "pending_no_signer",
        "to_address": "0xdest",
        "amount_usdc": 3.0,
        "tx_hash": None,
        "note": "eth_account not installed",
    }
    text = wallet_withdraw_result_screen(result)
    assert "QUEUED" in text
    assert "eth_account not installed" in text


# ── Keyboard tests ─────────────────────────────────────────────────────────────


def test_wr26_build_wallet_menu_has_withdraw():
    """WR-26: build_wallet_menu contains a Withdraw button."""
    from projects.polymarket.polyquantbot.telegram.ui.keyboard import build_wallet_menu
    kb = build_wallet_menu()
    all_callbacks = [btn["callback_data"] for row in kb for btn in row]
    assert "action:wallet_withdraw" in all_callbacks


# ── Callback router dispatch test ──────────────────────────────────────────────


async def test_wr27_callback_router_dispatches_wallet_withdraw():
    """WR-27: CallbackRouter._dispatch(wallet_withdraw) calls handle_wallet_withdraw."""
    from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter
    from projects.polymarket.polyquantbot.telegram.ui.screens import wallet_withdraw_screen
    from projects.polymarket.polyquantbot.telegram.ui.keyboard import build_wallet_menu

    mock_state = MagicMock()
    mock_state.snapshot.return_value = {"state": "RUNNING"}
    mock_config = MagicMock()

    router = CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=MagicMock(),
        state_manager=mock_state,
        config_manager=mock_config,
        mode="PAPER",
    )

    text, kb = await router._dispatch("wallet_withdraw", user_id=0)
    assert isinstance(text, str)
    assert "WITHDRAW" in text
    assert isinstance(kb, list)


# ── WalletRepository tests (WR-28+) ───────────────────────────────────────────


def _make_mock_db(rows=None):
    """Return a MagicMock DatabaseClient whose _fetch/_execute return canned data."""
    db = MagicMock()
    db._fetch = AsyncMock(return_value=rows if rows is not None else [])
    db._execute = AsyncMock(return_value=True)
    return db


async def test_wr28_repository_get_wallet_not_found():
    """WR-28: WalletRepository.get_wallet returns None when no DB row exists."""
    from projects.polymarket.polyquantbot.core.wallet.repository import WalletRepository

    db = _make_mock_db(rows=[])
    repo = WalletRepository(db)
    result = await repo.get_wallet(user_id=999)
    assert result is None


async def test_wr29_repository_get_wallet_returns_model():
    """WR-29: WalletRepository.get_wallet deserializes row to WalletModel."""
    from projects.polymarket.polyquantbot.core.wallet.repository import WalletRepository

    fake_row = {
        "user_id": 42,
        "address": "0xAbCdEf" + "0" * 34,
        "encrypted_private_key": "enc_blob",
        "created_at": 1700000000.0,
    }
    db = _make_mock_db(rows=[fake_row])
    repo = WalletRepository(db)
    wallet = await repo.get_wallet(user_id=42)
    assert wallet is not None
    assert wallet.user_id == 42
    assert wallet.address == fake_row["address"]
    assert wallet.encrypted_private_key == "enc_blob"
    assert wallet.created_at == 1700000000.0


async def test_wr30_repository_create_wallet_idempotent():
    """WR-30: WalletRepository.create_wallet returns existing wallet on conflict."""
    from projects.polymarket.polyquantbot.core.wallet.models import WalletModel
    from projects.polymarket.polyquantbot.core.wallet.repository import WalletRepository

    existing_row = {
        "user_id": 50,
        "address": "0x" + "a" * 40,
        "encrypted_private_key": "enc",
        "created_at": 1700000000.0,
    }
    db = _make_mock_db(rows=[existing_row])
    repo = WalletRepository(db)

    new_wallet = WalletModel(user_id=50, address="0x" + "b" * 40, encrypted_private_key="enc2")
    # _execute (INSERT) succeeds silently (DO NOTHING), then _fetch returns existing row
    returned = await repo.create_wallet(user_id=50, wallet=new_wallet)
    # Should return the row from DB, not the new wallet
    assert returned.address == existing_row["address"]


async def test_wr31_repository_ensure_schema_calls_execute():
    """WR-31: WalletRepository.ensure_schema calls _execute with CREATE TABLE DDL."""
    from projects.polymarket.polyquantbot.core.wallet.repository import WalletRepository

    db = _make_mock_db()
    repo = WalletRepository(db)
    await repo.ensure_schema()
    db._execute.assert_called_once()
    call_args = db._execute.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS wallets" in call_args


async def test_wr32_repository_update_wallet_calls_execute():
    """WR-32: WalletRepository.update_wallet calls _execute with UPDATE SQL."""
    from projects.polymarket.polyquantbot.core.wallet.models import WalletModel
    from projects.polymarket.polyquantbot.core.wallet.repository import WalletRepository

    db = _make_mock_db()
    repo = WalletRepository(db)
    wallet = WalletModel(user_id=77, address="0x" + "c" * 40, encrypted_private_key="enc")
    await repo.update_wallet(wallet)
    db._execute.assert_called_once()
    call_args = db._execute.call_args[0][0]
    assert "UPDATE wallets" in call_args


async def test_wr33_service_with_repository_uses_db():
    """WR-33: WalletService.get_wallet delegates to repository when injected."""
    from projects.polymarket.polyquantbot.core.wallet.service import WalletService
    from projects.polymarket.polyquantbot.core.wallet.repository import WalletRepository

    fake_row = {
        "user_id": 200,
        "address": "0x" + "d" * 40,
        "encrypted_private_key": "enc_blob",
        "created_at": 1700000000.0,
    }
    db = _make_mock_db(rows=[fake_row])
    repo = WalletRepository(db)
    svc = WalletService(http_session_factory=None, repository=repo)

    wallet = await svc.get_wallet(user_id=200)
    assert wallet is not None
    assert wallet.address == fake_row["address"]
    # Verify _fetch was called (not in-memory dict)
    db._fetch.assert_called_once()


async def test_wr34_service_with_repository_create_persists():
    """WR-34: WalletService.create_wallet persists via repository when injected."""
    from projects.polymarket.polyquantbot.core.wallet.service import WalletService
    from projects.polymarket.polyquantbot.core.wallet.repository import WalletRepository

    # First get_wallet → None (not found); then after create, insert returns a row
    created_address = None

    async def fake_fetch(sql, *args, op_label=""):
        if created_address is None:
            return []  # not found before creation
        return [{
            "user_id": 201,
            "address": created_address,
            "encrypted_private_key": "enc",
            "created_at": 1700000000.0,
        }]

    async def fake_execute(sql, *args, op_label=""):
        nonlocal created_address
        if "INSERT" in sql:
            # Capture the address from the args (position 1 = address)
            created_address = args[1]
        return True

    db = MagicMock()
    db._fetch = AsyncMock(side_effect=fake_fetch)
    db._execute = AsyncMock(side_effect=fake_execute)
    repo = WalletRepository(db)
    svc = WalletService(http_session_factory=None, repository=repo)

    wallet = await svc.create_wallet(user_id=201)
    assert wallet is not None
    assert wallet.address.startswith("0x")
    assert len(wallet.address) == 42  # valid Ethereum address length
    # Encrypted key must be present and not look like plaintext hex
    assert wallet.encrypted_private_key
    assert len(wallet.encrypted_private_key) != 64  # not a raw private key


async def test_wr35_generate_keypair_eth_address():
    """WR-35: _generate_keypair produces a valid EIP-55 Ethereum address."""
    from projects.polymarket.polyquantbot.core.wallet.service import _generate_keypair

    private_key_hex, address = _generate_keypair()
    # Private key: 64 hex chars, no 0x
    assert len(private_key_hex) == 64
    assert all(c in "0123456789abcdef" for c in private_key_hex)
    # Address: 0x + 40 hex chars
    assert address.startswith("0x")
    assert len(address) == 42
    # Address must be valid hex
    int(address[2:], 16)


async def test_wr36_handle_withdraw_command_success():
    """WR-36: handle_withdraw_command returns result screen with tx_hash on success."""
    import projects.polymarket.polyquantbot.telegram.handlers.wallet as wh
    from projects.polymarket.polyquantbot.core.wallet.service import WalletService

    svc = WalletService(http_session_factory=None)
    wh.set_wallet_service(svc)

    try:
        # Mock out the wallet service's withdraw to return a broadcast result
        mock_result = {
            "status": "broadcast",
            "from_address": "0x" + "a" * 40,
            "to_address": "0x" + "b" * 40,
            "amount_usdc": 5.0,
            "tx_hash": "0xdeadbeef1234",
        }
        svc.withdraw = AsyncMock(return_value=mock_result)

        text, kb = await wh.handle_withdraw_command(
            user_id=500,
            to_address="0x" + "b" * 40,
            amount_usdc=5.0,
        )
        assert "0xdeadbeef1234" in text
        assert "SUBMITTED" in text
        assert isinstance(kb, list)
    finally:
        wh._wallet_service = None


async def test_wr37_handle_withdraw_command_error_returns_error_screen():
    """WR-37: handle_withdraw_command returns error screen on ValueError."""
    import projects.polymarket.polyquantbot.telegram.handlers.wallet as wh
    from projects.polymarket.polyquantbot.core.wallet.service import WalletService

    svc = WalletService(http_session_factory=None)
    wh.set_wallet_service(svc)

    try:
        svc.withdraw = AsyncMock(side_effect=ValueError("Invalid destination address"))
        text, kb = await wh.handle_withdraw_command(
            user_id=600,
            to_address="bad",
            amount_usdc=1.0,
        )
        assert "Failed" in text or "WITHDRAW" in text
        assert isinstance(kb, list)
    finally:
        wh._wallet_service = None
