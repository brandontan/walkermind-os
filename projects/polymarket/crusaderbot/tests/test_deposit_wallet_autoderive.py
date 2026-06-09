"""POLY_1271 deposit-wallet auto-derivation (WARP/root-deposit-wallet-autoderive).

For a deposit wallet (signature type 3), the operator should NOT have to look up
and hardcode ``POLYMARKET_FUNDER_ADDRESS``: the configured signer key alone is
enough. ``ensure_clob_credentials`` resolves the signer's current deposit wallet
via the official ``polymarket`` SDK's ``AsyncSecureClient`` (which picks the
correct beacon/UUPS deterministic wallet on-chain), caches it in
``_derived_wallet``, and ``effective_funder`` hands that to the order client as
the maker/funder.

These tests mock ``AsyncSecureClient`` — no network, no key material.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.integrations import clob as clob_pkg

_RESOLVED = "0xe82cAf9536a0c96F91Ee912070a103c3F04c441E"


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


class _FakeCreds:
    key = "ak_test_12345678"
    secret = "secret_test"
    passphrase = "passphrase_test"


class _FakeSecureClient:
    """Stand-in for polymarket.AsyncSecureClient that records the requested wallet
    and returns the deterministic resolved wallet + creds."""

    last_requested: object = "UNSET"

    def __init__(self) -> None:
        self.wallet = _RESOLVED
        self.credentials = _FakeCreds()

    async def close(self) -> None:  # noqa: D401 - test stub
        return None

    @classmethod
    async def create(cls, *, private_key: str, wallet=None, **_kw):
        cls.last_requested = wallet
        return cls()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    crusaderbot_config.get_settings.cache_clear()
    clob_pkg._derived = None
    clob_pkg._derived_wallet = None
    _FakeSecureClient.last_requested = "UNSET"
    # The SDK is imported as ``from polymarket import AsyncSecureClient`` inside the
    # function, so patch the attribute on the ``polymarket`` module.
    import polymarket
    monkeypatch.setattr(polymarket, "AsyncSecureClient", _FakeSecureClient)
    yield
    crusaderbot_config.get_settings.cache_clear()
    clob_pkg._derived = None
    clob_pkg._derived_wallet = None


def _settings(monkeypatch, *, funder: str | None):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("USE_REAL_CLOB", "true")
    monkeypatch.setenv("USE_CLOB_V2", "true")
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "3")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0x" + "11" * 32)
    if funder is not None:
        monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", funder)
    else:
        monkeypatch.delenv("POLYMARKET_FUNDER_ADDRESS", raising=False)
    crusaderbot_config.get_settings.cache_clear()
    return crusaderbot_config.Settings()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_autoderive_resolves_wallet_when_funder_unset(monkeypatch):
    """No POLYMARKET_FUNDER_ADDRESS → the SDK is asked to auto-derive (wallet=None)
    and the resolved deposit wallet is cached."""
    s = _settings(monkeypatch, funder=None)
    await clob_pkg.ensure_clob_credentials(s)
    assert _FakeSecureClient.last_requested is None  # auto-derive requested
    assert clob_pkg._derived_wallet == _RESOLVED
    assert clob_pkg._derived["api_key"] == "ak_test_12345678"


@pytest.mark.asyncio
async def test_autoderive_passes_configured_funder_through(monkeypatch):
    """A configured funder is forwarded to the SDK for validation, and the
    SDK-resolved wallet is still the authoritative cache."""
    s = _settings(monkeypatch, funder=_RESOLVED)
    await clob_pkg.ensure_clob_credentials(s)
    assert _FakeSecureClient.last_requested == _RESOLVED
    assert clob_pkg._derived_wallet == _RESOLVED


@pytest.mark.asyncio
async def test_effective_funder_prefers_resolved_for_sig3(monkeypatch):
    s = _settings(monkeypatch, funder=None)
    # Before resolution, falls back to the (unset) env funder.
    assert clob_pkg.effective_funder(s) is None
    await clob_pkg.ensure_clob_credentials(s)
    # After resolution, the SDK wallet wins.
    assert clob_pkg.effective_funder(s) == _RESOLVED


def test_effective_funder_non_sig3_uses_env(monkeypatch):
    """Non-deposit-wallet types keep the env-configured funder (no auto-derive)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "2")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0x" + "22" * 20)
    crusaderbot_config.get_settings.cache_clear()
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    clob_pkg._derived_wallet = _RESOLVED  # even if a stale value is cached
    assert clob_pkg.effective_funder(s) == "0x" + "22" * 20


@pytest.mark.asyncio
async def test_get_clob_client_uses_resolved_funder(monkeypatch):
    """End-to-end: after auto-derive, the v2 client is built with the resolved
    deposit wallet as its funder."""
    s = _settings(monkeypatch, funder=None)
    await clob_pkg.ensure_clob_credentials(s)
    client = clob_pkg.get_clob_client(s)
    assert getattr(client, "funder", None) == _RESOLVED


def test_get_clob_client_sig3_fails_fast_when_unresolved(monkeypatch):
    """Gemini #1729: a sig-3 client with NO resolved wallet and NO env funder must
    fail fast with a clear message, not build a client with funder=None."""
    from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
        ClobConfigError,
    )

    s = _settings(monkeypatch, funder=None)  # USE_REAL_CLOB=True, sig 3
    # ensure_clob_credentials NOT run -> _derived_wallet stays None, env funder None.
    assert clob_pkg._derived_wallet is None
    with pytest.raises(ClobConfigError, match="deposit wallet"):
        clob_pkg.get_clob_client(s)


def test_get_clob_client_sig3_paper_mode_never_fails(monkeypatch):
    """Paper mode (USE_REAL_CLOB=False) returns the mock and never requires a
    resolved funder."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("USE_REAL_CLOB", "false")
    monkeypatch.setenv("POLYMARKET_SIGNATURE_TYPE", "3")
    monkeypatch.delenv("POLYMARKET_FUNDER_ADDRESS", raising=False)
    crusaderbot_config.get_settings.cache_clear()
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    client = clob_pkg.get_clob_client(s)
    assert client.__class__.__name__ == "MockClobClient"
