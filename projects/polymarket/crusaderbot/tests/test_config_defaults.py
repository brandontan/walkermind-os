"""Activation-guard default posture.

ENABLE_LIVE_TRADING must default to False so a dev/test/local boot WITHOUT
fly.toml can never silently arm live trading. Production behaviour is
unchanged — fly.toml explicitly forces the same value.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


def test_enable_live_trading_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)

    settings = crusaderbot_config.Settings()  # type: ignore[call-arg]

    assert settings.ENABLE_LIVE_TRADING is False
    crusaderbot_config.get_settings.cache_clear()


def test_enable_live_trading_explicit_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")

    settings = crusaderbot_config.Settings()  # type: ignore[call-arg]

    assert settings.ENABLE_LIVE_TRADING is True
    crusaderbot_config.get_settings.cache_clear()


def test_other_activation_guards_default_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)

    settings = crusaderbot_config.Settings()  # type: ignore[call-arg]

    assert settings.EXECUTION_PATH_VALIDATED is False
    assert settings.CAPITAL_MODE_CONFIRMED is False
    assert settings.RISK_CONTROLS_VALIDATED is False
    crusaderbot_config.get_settings.cache_clear()
