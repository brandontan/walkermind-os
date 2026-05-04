"""CrusaderBot configuration via pydantic-settings.

All required env vars MUST be present at startup or import fails fast.
Activation guards default to False — flipping requires explicit env override.
"""
from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    TELEGRAM_BOT_TOKEN: str
    OPERATOR_CHAT_ID: int
    DATABASE_URL: str
    REDIS_URL: str
    POLYGON_RPC_URL: str
    # Reserved for future eth_getLogs reconciliation pass (R4.1 backfill lane).
    # Optional until a caller actually uses it — making it required causes
    # startup failure with no functional benefit in R4.
    ALCHEMY_POLYGON_RPC_URL: Optional[str] = None
    ALCHEMY_POLYGON_WS_URL: str
    USDC_CONTRACT_ADDRESS: str
    MASTER_WALLET_ADDRESS: str
    MASTER_WALLET_PRIVATE_KEY: str
    WALLET_HD_SEED: str
    WALLET_ENCRYPTION_KEY: str
    POLYMARKET_API_KEY: str
    POLYMARKET_API_SECRET: str
    POLYMARKET_PASSPHRASE: str

    ENABLE_LIVE_TRADING: bool = False
    EXECUTION_PATH_VALIDATED: bool = False
    CAPITAL_MODE_CONFIRMED: bool = False
    FEE_COLLECTION_ENABLED: bool = False
    AUTO_REDEEM_ENABLED: bool = False

    APP_ENV: str = "development"
    MIN_DEPOSIT_USDC: float = 50.0
    MARKET_SCAN_INTERVAL: int = 300
    DEPOSIT_WATCH_INTERVAL: int = 120
    DB_POOL_MAX: int = 5

    @property
    def guard_states(self) -> dict[str, bool]:
        return {
            "ENABLE_LIVE_TRADING": self.ENABLE_LIVE_TRADING,
            "EXECUTION_PATH_VALIDATED": self.EXECUTION_PATH_VALIDATED,
            "CAPITAL_MODE_CONFIRMED": self.CAPITAL_MODE_CONFIRMED,
            "FEE_COLLECTION_ENABLED": self.FEE_COLLECTION_ENABLED,
            "AUTO_REDEEM_ENABLED": self.AUTO_REDEEM_ENABLED,
        }


settings = Settings()
