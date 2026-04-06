"""Startup environment/config validation for PolyQuantBot infra readiness."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List
from urllib.parse import urlparse


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
    parsed = urlparse(db_dsn)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DB_DSN must use postgres/postgresql scheme")

    db_host = (parsed.hostname or "").strip()
    db_port = int(parsed.port or 5432)
    db_name = parsed.path.lstrip("/").strip()
    db_user = (parsed.username or "").strip()

    missing: List[str] = []
    if not db_host:
        missing.append("DB host")
    if not db_name:
        missing.append("DB name")
    if not db_user:
        missing.append("DB user")
    if db_port <= 0 or db_port > 65535:
        raise ValueError("DB port must be between 1 and 65535")

    if missing:
        raise ValueError("Invalid DB_DSN; missing " + ", ".join(missing))

    return StartupConfig(
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
    )


def validate_startup_environment(mode: str) -> StartupConfig:
    """Validate startup environment consistency before runtime begins."""
    db_dsn = _read_env("DB_DSN")
    if not db_dsn:
        raise ValueError("Missing required DB_DSN environment variable")

    cfg = parse_db_dsn(db_dsn)

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
