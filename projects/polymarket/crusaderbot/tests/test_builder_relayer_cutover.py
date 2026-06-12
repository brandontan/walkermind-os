"""Polymarket Builder/Relayer cutover truth.

Pins the issue #1776 contracts that must remain true when the operator moves
from legacy Builder-only secrets to the current Builder + dedicated Relayer key
model. No secret values are logged or asserted beyond fixture sentinels.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from projects.polymarket.crusaderbot.services.validation.live_readiness_truth import live_readiness_truth
from projects.polymarket.crusaderbot.config import Settings
from projects.polymarket.crusaderbot.integrations import builder_relayer

_BASE_ENV = dict(
    TELEGRAM_BOT_TOKEN="tok",
    OPERATOR_CHAT_ID="1",
    DATABASE_URL="postgresql://x",
    WALLET_HD_SEED="seed",
    WALLET_ENCRYPTION_KEY="k",
    POLYGON_RPC_URL="https://rpc",
)


def test_poly_builder_api_secret_alias_populates_internal_relayer_secret(monkeypatch):
    """Legacy POLY_BUILDER_API_SECRET remains accepted; canonical wins later."""
    for key, value in _BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("POLY_BUILDER_API_KEY", "builder-key")
    monkeypatch.setenv("POLY_BUILDER_API_SECRET", "legacy-secret")
    monkeypatch.setenv("POLY_BUILDER_PASSPHRASE", "builder-pass")

    settings = Settings()

    assert settings.POLY_BUILDER_SECRET == "legacy-secret"


def test_canonical_poly_builder_secret_wins_over_api_secret_alias(monkeypatch):
    for key, value in _BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("POLY_BUILDER_SECRET", "canonical-secret")
    monkeypatch.setenv("POLY_BUILDER_API_SECRET", "legacy-secret")

    settings = Settings()

    assert settings.POLY_BUILDER_SECRET == "canonical-secret"


def test_relayer_api_key_is_reported_separately_from_builder_creds():
    settings = SimpleNamespace(
        USE_BUILDER_RELAYER=True,
        RELAYER_API_KEY="relayer-key",
        RELAYER_API_KEY_ADDRESS="0x" + "11" * 20,
        POLY_BUILDER_API_KEY=None,
        POLY_BUILDER_SECRET=None,
        POLY_BUILDER_PASSPHRASE=None,
        USE_REAL_CLOB=False,
        USE_PER_USER_EXECUTION=False,
        CUSTODY_MODE="safe",
        POLYMARKET_FUNDER_ADDRESS="0x" + "22" * 20,
        POLYMARKET_SIGNATURE_TYPE=2,
        POLYMARKET_BUILDER_CODE=None,
        POLYMARKET_BUILDER_ADDRESS=None,
        EXECUTION_PATH_VALIDATED=False,
    )

    truth = live_readiness_truth(settings)

    assert truth["relayer_configured"] is True
    assert truth["relayer_api_key_address_configured"] is True
    assert truth["builder_configured"] is False
    assert truth["custody_mode"] == "safe"
    assert truth["funder_deposit_wallet_source"] == "POLYMARKET_FUNDER_ADDRESS"


def test_builder_creds_reported_without_collapsing_execution_guards():
    settings = SimpleNamespace(
        USE_BUILDER_RELAYER=True,
        RELAYER_API_KEY=None,
        RELAYER_API_KEY_ADDRESS=None,
        POLY_BUILDER_API_KEY="builder-key",
        POLY_BUILDER_SECRET="builder-secret",
        POLY_BUILDER_PASSPHRASE="builder-pass",
        USE_REAL_CLOB=False,
        USE_PER_USER_EXECUTION=True,
        CUSTODY_MODE="eoa",
        POLYMARKET_FUNDER_ADDRESS=None,
        POLYMARKET_SIGNATURE_TYPE=2,
        POLYMARKET_BUILDER_CODE="0x" + "ab" * 32,
        POLYMARKET_BUILDER_ADDRESS="0x" + "cd" * 20,
        EXECUTION_PATH_VALIDATED=False,
    )

    truth = live_readiness_truth(settings)

    assert truth["relayer_configured"] is True
    assert truth["relayer_api_key_address_configured"] is False
    assert truth["builder_configured"] is True
    assert truth["real_clob_armed"] is False
    assert truth["execution_path_validated"] is False
    assert truth["custody_mode"] == "deposit_wallet"
    assert truth["funder_deposit_wallet_source"] == "per_user_deposit_wallet"
    assert truth["builder_code_configured"] is True
    assert truth["builder_address_configured"] is True


def test_builder_relayer_distinguishes_sdk_relayer_key_from_builder_client_creds():
    settings = SimpleNamespace(
        USE_BUILDER_RELAYER=True,
        RELAYER_API_KEY="relayer-key",
        RELAYER_API_KEY_ADDRESS="0x" + "11" * 20,
        POLY_BUILDER_API_KEY=None,
        POLY_BUILDER_SECRET=None,
        POLY_BUILDER_PASSPHRASE=None,
    )

    with patch.object(builder_relayer, "get_settings", return_value=settings):
        assert builder_relayer.is_relayer_api_key_configured() is True
        assert builder_relayer.is_builder_configured() is False
        assert builder_relayer.is_relayer_configured() is False
