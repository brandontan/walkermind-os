"""Application configuration — loaded from environment, fail-fast on missing secrets."""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Names checked at boot by ``validate_required_env``. Missing entries are
# logged at ERROR (key only — values are NEVER logged) so the operator alert
# layer can surface a degraded state without crashing the process.
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "TELEGRAM_BOT_TOKEN",
    "DATABASE_URL",
    "ALCHEMY_POLYGON_WS_URL",
    "OPERATOR_CHAT_ID",
    "WALLET_ENCRYPTION_KEY",
)

# "At least one of" groups: validation passes for the group when any of its
# members resolves to a non-empty value. ``check_alchemy_rpc`` falls back to
# the legacy ``POLYGON_RPC_URL`` when the Alchemy alias is unset, so a
# deployment using only the legacy name is healthy and must NOT be paged.
REQUIRED_ENV_VAR_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ALCHEMY_POLYGON_RPC_URL", "POLYGON_RPC_URL"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Required at startup ---
    TELEGRAM_BOT_TOKEN: str
    OPERATOR_CHAT_ID: int
    DATABASE_URL: str
    POLYGON_RPC_URL: str
    WALLET_HD_SEED: str
    WALLET_ENCRYPTION_KEY: str

    # --- Alchemy endpoints (optional aliases used by deposit watcher + health) ---
    # Falling back through ``ALCHEMY_POLYGON_RPC_URL`` lets operators provide a
    # single Alchemy URL without renaming the legacy ``POLYGON_RPC_URL``.
    ALCHEMY_POLYGON_RPC_URL: Optional[str] = None
    ALCHEMY_POLYGON_WS_URL: Optional[str] = None

    # --- Optional infra ---
    REDIS_URL: Optional[str] = None  # falls back to in-memory cache if missing

    # --- Telegram webhook (set to use webhook mode instead of polling) ---
    # Example: https://my-app.fly.dev/telegram/webhook
    TELEGRAM_WEBHOOK_URL: Optional[str] = None
    # Random secret to validate that updates come from Telegram (auto-generated
    # if not set, but setting it explicitly lets you rotate it without redeploying).
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None

    # --- Admin REST API (disabled when unset) ---
    ADMIN_API_TOKEN: Optional[str] = None

    # --- Polymarket (only required for LIVE trading) ---
    POLYMARKET_API_KEY: Optional[str] = None
    POLYMARKET_API_SECRET: Optional[str] = None
    POLYMARKET_PASSPHRASE: Optional[str] = None

    # --- Polygon ---
    USDC_POLYGON: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_DECIMALS: int = 6

    # --- Master / hot-pool wallet (derived from HD seed index 0 if not set) ---
    MASTER_WALLET_ADDRESS: Optional[str] = None
    MASTER_WALLET_PRIVATE_KEY: Optional[str] = None

    # --- Activation guards ---
    # Per user revision: live engine is fully built and reachable.
    # Default for every NEW USER/TRADE is still paper. Live requires
    # ALL guards true + Tier 4 user approval.
    ENABLE_LIVE_TRADING: bool = True
    EXECUTION_PATH_VALIDATED: bool = False
    CAPITAL_MODE_CONFIRMED: bool = False
    FEE_COLLECTION_ENABLED: bool = False
    AUTO_REDEEM_ENABLED: bool = True

    # --- App config ---
    APP_ENV: str = "development"
    PORT: int = 8080
    HOST: str = "0.0.0.0"
    MIN_DEPOSIT_USDC: float = 50.0
    MARKET_SCAN_INTERVAL: int = 300
    DEPOSIT_WATCH_INTERVAL: int = 120
    SIGNAL_SCAN_INTERVAL: int = 180
    EXIT_WATCH_INTERVAL: int = 60
    REDEEM_INTERVAL: int = 3600
    RESOLUTION_CHECK_INTERVAL: int = 300
    DB_POOL_MAX: int = 5
    TIMEZONE: str = "Asia/Jakarta"

    # --- Instant redeem gas guard (R10): if Polygon gas exceeds this when a
    # live position becomes redeemable, defer to the hourly queue. ---
    INSTANT_REDEEM_GAS_GWEI_MAX: float = 200.0

    @model_validator(mode="before")
    @classmethod
    def _alias_polygon_rpc_url(cls, data):
        """Allow alias-only deployments: when only ``ALCHEMY_POLYGON_RPC_URL``
        is supplied, copy it into ``POLYGON_RPC_URL`` so the latter's
        ``str`` (required) field is satisfied. ``validate_required_env``
        and ``check_alchemy_rpc`` both accept either name; this keeps
        ``Settings`` consistent with that contract instead of raising a
        validation error at boot in the alias-only path.
        """
        if isinstance(data, dict):
            legacy = data.get("POLYGON_RPC_URL")
            alias = data.get("ALCHEMY_POLYGON_RPC_URL")
            if (legacy is None or str(legacy).strip() == "") and alias:
                data["POLYGON_RPC_URL"] = alias
        return data

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # asyncpg.create_pool accepts postgres:// and postgresql:// but NOT
        # the SQLAlchemy-style "postgresql+asyncpg://" prefix.
        if v.startswith("postgresql+asyncpg://"):
            return "postgresql://" + v[len("postgresql+asyncpg://"):]
        if v.startswith("postgres://"):
            return "postgresql://" + v[len("postgres://"):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def _load_env_file_values() -> dict[str, str]:
    """Read the same ``.env`` file ``Settings`` consumes, without overriding
    real environment values. Missing or unreadable files yield an empty
    dict — validation must never crash boot.

    Path resolution intentionally matches ``SettingsConfigDict(env_file=".env")``
    exactly: cwd-relative only. A module-dir fallback would read a file
    that ``get_settings()`` will NOT read, which could suppress missing-env
    alerts the operator needs to see and let boot fail later with a
    ``ValidationError`` instead.
    """
    path = Path(".env")
    if not path.exists():
        return {}
    try:
        from dotenv import dotenv_values

        return {k: v for k, v in dotenv_values(str(path)).items() if v is not None}
    except Exception as exc:  # noqa: BLE001 — never crash boot on .env read
        logger.warning(
            "config validation: .env read failed at %s: %s", path, exc,
        )
        return {}


def validate_required_env() -> list[str]:
    """Return the list of REQUIRED env vars that are missing at boot.

    Reads from the same sources ``Settings`` consumes: ``os.environ`` plus
    the ``.env`` file (when present). Logs an ERROR line per missing
    variable (key name only — values are NEVER logged). The process is
    allowed to continue so that the health endpoint can surface the
    degraded state via the operator alert path. Callers must NOT log the
    returned values; they are key names only.
    """
    resolved: dict[str, str] = dict(os.environ)
    for key, value in _load_env_file_values().items():
        # os.environ wins over .env, matching pydantic-settings precedence.
        if key not in resolved:
            resolved[key] = value

    def _has(key: str) -> bool:
        return bool((resolved.get(key) or "").strip())

    missing: list[str] = [k for k in REQUIRED_ENV_VARS if not _has(k)]
    for group in REQUIRED_ENV_VAR_GROUPS:
        if not any(_has(name) for name in group):
            # Report the group as a single composite key so the operator
            # sees both candidate names without two duplicate alerts.
            missing.append(" or ".join(group))
    for key in missing:
        logger.error("required env var missing: %s", key)
    return missing
