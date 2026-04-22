"""Startup environment/config validation for PolyQuantBot infra readiness."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from projects.polymarket.polyquantbot.infra.db.runtime_config import (
    load_database_runtime_config,
    parse_database_runtime_dsn,
)


@dataclass(frozen=True)
class StartupConfig:
    db_host: str
    db_port: int
    db_name: str
    db_user: str


_REQUIRED_SECRETS_COMMON: tuple[str, ...] = (
    "TELEGRAM_CHAT_ID",
)
_REQUIRED_SECRETS_PIPELINE: tuple[str, ...] = (
    "CLOB_API_KEY",
    "CLOB_API_SECRET",
    "CLOB_API_PASSPHRASE",
)
_TELEGRAM_TOKEN_ALIASES: tuple[str, ...] = ("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN")


def _read_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _get_telegram_token() -> str:
    for alias in _TELEGRAM_TOKEN_ALIASES:
        value = _read_env(alias)
        if value:
            return value
    return ""


def parse_db_dsn(db_dsn: str) -> StartupConfig:
    """Compatibility parser for legacy call sites using DB_DSN naming."""
    cfg = parse_database_runtime_dsn(raw_dsn=db_dsn, source="DB_DSN_COMPAT")
    return StartupConfig(
        db_host=cfg.host,
        db_port=cfg.port,
        db_name=cfg.database,
        db_user=cfg.user,
    )


def validate_startup_environment(mode: str) -> StartupConfig:
    """Validate startup environment consistency before runtime begins."""
    db_cfg = load_database_runtime_config()
    cfg = StartupConfig(
        db_host=db_cfg.host,
        db_port=db_cfg.port,
        db_name=db_cfg.database,
        db_user=db_cfg.user,
    )

    missing_secrets: List[str] = []
    if not _get_telegram_token():
        missing_secrets.append("TELEGRAM_TOKEN or TELEGRAM_BOT_TOKEN")

    for name in _REQUIRED_SECRETS_COMMON:
        if not _read_env(name):
            missing_secrets.append(name)

    # Pipeline secrets are required in both PAPER/LIVE because startup bootstraps
    # market data + signal pipeline in all modes.
    for name in _REQUIRED_SECRETS_PIPELINE:
        if not _read_env(name):
            missing_secrets.append(name)

    if missing_secrets:
        raise ValueError(
            "Missing required startup secrets: " + ", ".join(missing_secrets)
        )

    enable_live = _read_env("ENABLE_LIVE_TRADING").lower() == "true"
    if mode.upper() == "LIVE" and not enable_live:
        raise ValueError(
            "TRADING_MODE=LIVE requires ENABLE_LIVE_TRADING=true"
        )
    if mode.upper() == "PAPER" and enable_live:
        raise ValueError(
            "ENABLE_LIVE_TRADING=true is inconsistent with TRADING_MODE=PAPER"
        )

    return cfg
