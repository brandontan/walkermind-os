"""Application configuration — loaded from environment, fail-fast on missing secrets."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
