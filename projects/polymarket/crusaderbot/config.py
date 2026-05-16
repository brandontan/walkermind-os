"""Application configuration — loaded from environment, fail-fast on missing secrets."""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator, model_validator
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
    "WALLET_HD_SEED",
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

    # --- WebTrader browser dashboard (disabled when unset) ---
    # JWT secret for signing user tokens issued after Telegram Login Widget auth.
    # Generate: openssl rand -hex 32
    # Set in Fly.io: fly secrets set WEBTRADER_JWT_SECRET=<value>
    WEBTRADER_JWT_SECRET: Optional[str] = None

    # --- /ops dashboard write controls (disabled when unset) ---
    # GET /ops stays open (read-only operator console). POST /ops/kill +
    # POST /ops/resume require this shared secret via the ``X-Ops-Token``
    # header OR ``?token=<value>`` query param. Disabled (503) when this
    # value is unset. Full auth hardening (per-operator login, rotation,
    # token-out-of-URL) is an INTENTIONAL documented deferral for the
    # paper-mode beta — tracked in PROJECT_STATE KNOWN ISSUES, rationale
    # in the ``api/ops.py`` module docstring. Not an incomplete stub.
    OPS_SECRET: Optional[str] = None

    # --- Sentry-related app metadata ---
    # SENTRY_DSN and SENTRY_TRACES_SAMPLE_RATE are intentionally NOT declared
    # on Settings: monitoring.sentry reads them directly from os.environ to
    # keep Sentry init independent of the rest of the app config (a
    # malformed sample-rate env value would otherwise break every later
    # get_settings() call and turn an optional observability knob into a
    # boot blocker — see Codex P2 on PR #901).
    #
    # APP_VERSION is kept here because /health surfaces it; Optional[str]
    # cannot fail validation, so this stays safe.
    APP_VERSION: Optional[str] = None

    # --- Heisenberg / Falcon API (market data + signal enrichment) ---
    HEISENBERG_API_TOKEN: Optional[str] = None

    # --- Polymarket (only required for LIVE trading) ---
    POLYMARKET_API_KEY: Optional[str] = None
    POLYMARKET_API_SECRET: Optional[str] = None
    # Legacy name (still consumed by integrations.polymarket._build_clob_client
    # which wraps py-clob-client). New ClobAdapter (Phase 4A) reads
    # POLYMARKET_API_PASSPHRASE first, falling back to POLYMARKET_PASSPHRASE.
    POLYMARKET_PASSPHRASE: Optional[str] = None
    POLYMARKET_API_PASSPHRASE: Optional[str] = None
    # L1 (EIP-712) signing key used by ClobAdapter to derive API credentials
    # and prove wallet ownership. Distinct from MASTER_WALLET_PRIVATE_KEY so
    # the trading signer can be rotated independently from the hot pool.
    POLYMARKET_PRIVATE_KEY: Optional[str] = None
    # Funder address (Gnosis Safe / proxy wallet that holds USDC + CTF) used
    # in L2 signature_type=GNOSIS_SAFE flow. None = funder defaults to signer.
    POLYMARKET_FUNDER_ADDRESS: Optional[str] = None
    # Signature type for L2 order signing: 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE.
    # Default 2 matches the most common Polymarket account shape.
    POLYMARKET_SIGNATURE_TYPE: int = 2

    # --- Polymarket builder program (optional, order attribution) ---
    POLYMARKET_BUILDER_API_KEY: Optional[str] = None
    POLYMARKET_BUILDER_API_SECRET: Optional[str] = None
    POLYMARKET_BUILDER_PASSPHRASE: Optional[str] = None

    # --- ClobAdapter toggle (Phase 4A) ---
    # Default False keeps every caller on MockClobClient (paper-safe). Real
    # network calls are unreachable until an operator flips this AND every
    # other activation guard. See docs/runbooks/clob-adapter.md (TBD).
    USE_REAL_CLOB: bool = False

    # --- Polygon ---
    USDC_POLYGON: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_DECIMALS: int = 6

    # --- Master / hot-pool wallet (derived from HD seed index 0 if not set) ---
    MASTER_WALLET_ADDRESS: Optional[str] = None
    MASTER_WALLET_PRIVATE_KEY: Optional[str] = None

    # --- Activation guards ---
    # Paper-safe default: False. A live order is only ever reachable when an
    # operator EXPLICITLY overrides this via env (fly.toml / .env) AND every
    # other guard below is true AND the user is Tier 4. Defaulting False means
    # a dev/test/local boot WITHOUT fly.toml can never silently arm live
    # trading. Production behaviour is unchanged — fly.toml forces this false.
    ENABLE_LIVE_TRADING: bool = False
    EXECUTION_PATH_VALIDATED: bool = False
    CAPITAL_MODE_CONFIRMED: bool = False
    # Set to True ONLY after WARP•SENTINEL validates the risk assertion layer
    # (domain.risk.hardening.audit_risk_constants returns passed=True and the
    # readiness validator issues PASS on all checks).  Never set without an
    # explicit WARP🔹CMD decision backed by a SENTINEL report.
    RISK_CONTROLS_VALIDATED: bool = False
    FEE_COLLECTION_ENABLED: bool = False
    REFERRAL_PAYOUT_ENABLED: bool = False
    AUTO_REDEEM_ENABLED: bool = True

    # --- App config ---
    APP_ENV: str = "development"
    PORT: int = 8080
    HOST: str = "0.0.0.0"
    MIN_DEPOSIT_USDC: float = 50.0
    MARKET_SCAN_INTERVAL: int = 300
    DEPOSIT_WATCH_INTERVAL: int = 120
    SIGNAL_SCAN_INTERVAL: int = 180
    MARKET_SIGNAL_SCAN_INTERVAL: int = 60
    COPY_TRADE_MONITOR_INTERVAL: int = 60  # Fast Track B — copy trade tick cadence
    EXIT_WATCH_INTERVAL: int = 60
    REDEEM_INTERVAL: int = 3600
    RESOLUTION_CHECK_INTERVAL: int = 300
    DB_POOL_MAX: int = 5
    TIMEZONE: str = "Asia/Jakarta"

    # --- Instant redeem gas guard (R10): if Polygon gas exceeds this when a
    # live position becomes redeemable, defer to the hourly queue. ---
    INSTANT_REDEEM_GAS_GWEI_MAX: float = 200.0

    # --- Order lifecycle polling (Phase 4C) ---
    # Interval between OrderLifecycleManager.poll_once ticks. Default 30s
    # gives a snappy dashboard without hammering the broker API.
    ORDER_POLL_INTERVAL_SECONDS: int = 30
    # Max consecutive poll attempts before an order is marked 'stale'
    # and the operator paged. Default 48 ticks * 30s = 24 minutes per
    # order before manual reconciliation.
    ORDER_POLL_MAX_ATTEMPTS: int = 48

    # --- CLOB WebSocket (Phase 4D) ---
    # Polymarket exposes two WS channels:
    #   wss://ws-subscriptions-clob.polymarket.com/ws/user    -> user fills + orders
    #   wss://ws-subscriptions-clob.polymarket.com/ws/market  -> market data
    # Phase 4D consumes the user channel only. The client opens the
    # socket only when USE_REAL_CLOB=True; paper mode never touches
    # the network.
    CLOB_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    # Reconnect backoff cap. Initial delay 1s, doubled per attempt with
    # +/-25% jitter, clipped at this value. Default 60s matches the
    # Polymarket guidance for keep-alive backoff.
    WS_RECONNECT_MAX_DELAY_SECONDS: int = 60
    # Polymarket recycles connections that go ~10s without a heartbeat,
    # so the client sends literal "PING" text every 10s and the peer
    # echoes "PONG"; the timeout window adds the same again before we
    # treat the socket as dead.
    WS_HEARTBEAT_INTERVAL_SECONDS: int = 10
    WS_HEARTBEAT_TIMEOUT_SECONDS: int = 10
    # APScheduler watchdog interval for the WebSocket client. Fires
    # every N seconds and reconnects when ``client.is_alive()`` is
    # False, covering both clean exits and silent socket deaths the
    # heartbeat path missed.
    WS_WATCHDOG_INTERVAL_SECONDS: int = 60

    # --- CLOB resilience (Phase 4E) ---
    # Number of consecutive transport failures (rate limit / 5xx /
    # timeout / network / max-retries) that trip the breaker from
    # CLOSED to OPEN. Auth-class errors (400/401/403) do NOT count --
    # those are operator-credential issues, not transport incidents.
    CIRCUIT_BREAKER_THRESHOLD: int = 5
    # Time the breaker stays OPEN before auto-transitioning to
    # HALF_OPEN. A successful trial in HALF_OPEN closes the breaker;
    # a failed trial re-opens it and restarts this window.
    CIRCUIT_BREAKER_RESET_SECONDS: int = 60
    # Token-bucket rate limiter applied to every outbound CLOB call.
    # Set below Polymarket's per-account ceiling so we throttle
    # locally before the broker's 429 path triggers.
    CLOB_RATE_LIMIT_RPS: int = 10

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
