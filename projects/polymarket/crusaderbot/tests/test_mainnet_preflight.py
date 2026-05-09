"""Unit tests for scripts/mainnet_preflight.py.

Builds a synthetic ``Settings`` object via ``model_construct`` so the
test does NOT touch ``os.environ`` and does NOT require the full set of
env vars Settings normally validates at boot. The point of the test is
the check logic, not the env loader.
"""
from __future__ import annotations

import base64

import pytest

from projects.polymarket.crusaderbot.config import Settings
from projects.polymarket.crusaderbot.scripts.mainnet_preflight import (
    DEFAULT_CHECKS,
    _check_activation_guards,
    _check_eip712_sign,
    _check_hmac_headers,
    _check_polymarket_secrets,
    _check_use_real_clob,
    run_preflight,
)


VALID_PK = "0x" + ("aa" * 32)
VALID_SECRET = base64.urlsafe_b64encode(
    b"test-secret-32-bytes-for-hmac-aa"
).decode()


def _settings(**overrides) -> Settings:
    """Build a Settings instance bypassing env validation.

    ``model_construct`` skips validators -- safe here because the
    preflight checks read attributes by name and don't care about
    field-level coercion (the live boot path still validates).
    """
    base = dict(
        TELEGRAM_BOT_TOKEN="t",
        OPERATOR_CHAT_ID=1,
        DATABASE_URL="postgresql://x",
        POLYGON_RPC_URL="https://x",
        WALLET_HD_SEED="seed",
        WALLET_ENCRYPTION_KEY="k",
        ENABLE_LIVE_TRADING=True,
        EXECUTION_PATH_VALIDATED=True,
        CAPITAL_MODE_CONFIRMED=True,
        FEE_COLLECTION_ENABLED=False,
        AUTO_REDEEM_ENABLED=True,
        USE_REAL_CLOB=True,
        POLYMARKET_API_KEY="api",
        POLYMARKET_API_SECRET=VALID_SECRET,
        POLYMARKET_API_PASSPHRASE="pp",
        POLYMARKET_PASSPHRASE=None,
        POLYMARKET_PRIVATE_KEY=VALID_PK,
        POLYMARKET_FUNDER_ADDRESS=None,
        POLYMARKET_SIGNATURE_TYPE=2,
    )
    base.update(overrides)
    return Settings.model_construct(**base)


# --- happy path ----------------------------------------------------


def test_all_checks_pass_with_valid_settings():
    s = _settings()
    all_pass, results = run_preflight(settings=s)
    assert all_pass is True
    assert all(r.passed for r in results)
    names = [r.name for r in results]
    assert names == [
        "activation_guards",
        "polymarket_secrets",
        "use_real_clob",
        "eip712_sign",
        "hmac_headers",
    ]


def test_default_checks_tuple_is_complete():
    # Guards against accidental drop of a check from the ordered list.
    assert len(DEFAULT_CHECKS) == 5


# --- per-check failures -------------------------------------------


def test_activation_guard_failure_short_circuits():
    s = _settings(ENABLE_LIVE_TRADING=False)
    res = _check_activation_guards(s)
    assert res.passed is False
    assert "ENABLE_LIVE_TRADING" in res.detail


def test_missing_polymarket_secret_fails():
    s = _settings(POLYMARKET_API_KEY=None)
    res = _check_polymarket_secrets(s)
    assert res.passed is False
    assert "POLYMARKET_API_KEY" in res.detail


def test_passphrase_legacy_alias_accepted():
    s = _settings(
        POLYMARKET_API_PASSPHRASE=None,
        POLYMARKET_PASSPHRASE="legacy-pp",
    )
    res = _check_polymarket_secrets(s)
    assert res.passed is True


def test_use_real_clob_false_fails():
    s = _settings(USE_REAL_CLOB=False)
    res = _check_use_real_clob(s)
    assert res.passed is False


def test_eip712_sign_with_bad_private_key_fails():
    s = _settings(POLYMARKET_PRIVATE_KEY="0xnot-a-real-key")
    res = _check_eip712_sign(s)
    assert res.passed is False


def test_eip712_sign_with_unset_private_key_fails():
    s = _settings(POLYMARKET_PRIVATE_KEY=None)
    res = _check_eip712_sign(s)
    assert res.passed is False
    assert "not SET" in res.detail


def test_hmac_with_bad_secret_fails():
    s = _settings(POLYMARKET_API_SECRET="!!!not-base64!!!")
    res = _check_hmac_headers(s)
    assert res.passed is False


# --- aggregate failure path ---------------------------------------


def test_run_preflight_returns_false_on_any_failure():
    s = _settings(EXECUTION_PATH_VALIDATED=False)
    all_pass, results = run_preflight(settings=s)
    assert all_pass is False
    failed = [r for r in results if not r.passed]
    assert any(r.name == "activation_guards" for r in failed)


def test_no_broker_call_in_preflight(monkeypatch):
    """Defense-in-depth: assert the preflight never touches httpx.

    If a future check ever introduces a network call by mistake, this
    test fires before the operator runs the script against mainnet.
    """
    import httpx as _httpx  # imported here to monkeypatch the symbol

    def _explode(*args, **kwargs):
        raise AssertionError("preflight made a network call -- forbidden")

    monkeypatch.setattr(_httpx.AsyncClient, "request", _explode, raising=True)
    monkeypatch.setattr(_httpx.AsyncClient, "get", _explode, raising=True)
    monkeypatch.setattr(_httpx.AsyncClient, "post", _explode, raising=True)

    s = _settings()
    all_pass, _ = run_preflight(settings=s)
    assert all_pass is True
