"""Production bootstrap for PolyQuantBot.

Responsibilities:
  1. Load environment variables (via dotenv if available).
  2. Validate required credentials — raise RuntimeError on missing values.
  3. Fill optional configuration with safe production defaults.
  4. Perform automatic market discovery when MARKET_IDS is not supplied:
       - Fetch active markets from the Gamma REST API.
       - Filter by liquidity > 10k USD.
       - Select the top-N by volume (N = MAX_MARKETS, default 5).
       - Raise RuntimeError if no qualifying markets are found (hard fail).

Usage::

    from projects.polymarket.polyquantbot.core.bootstrap import run_bootstrap

    cfg, market_ids = await run_bootstrap()
    # cfg  — pipeline configuration dict ready for LivePaperRunner / Phase10PipelineRunner
    # market_ids — list of Polymarket condition IDs to subscribe to

Required environment variables:
    CLOB_API_KEY
    CLOB_API_SECRET
    CLOB_API_PASSPHRASE
    TELEGRAM_TOKEN   (alias: TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID

Optional environment variables (with defaults):
    MODE / TRADING_MODE    — PAPER | LIVE  (default: PAPER)
    MAX_MARKETS            — int  (default: 5)
    MARKET_IDS             — comma-separated condition IDs; disables auto-discovery
                             set to "auto" or leave unset to enable auto-discovery
    CLOB_WS_URL            — WebSocket URL override
    MAX_CAPITAL_USD        — float (default: 10000)
    MAX_TRADES_PER_DAY     — int   (default: 200)
    DAILY_LOSS_LIMIT       — float (default: -2000)
    MAX_DRAWDOWN_PCT       — float (default: 0.08)
    MIN_LIQUIDITY_USD      — float (default: 10000)
    MAX_POSITION_USD       — float (default: 1000)
    MAX_SLIPPAGE_PCT       — float (default: 0.03)
    HEALTH_LOG_INTERVAL_S  — float (default: 60)
    WS_HEARTBEAT_TIMEOUT_S — float (default: 30)
    WS_RECONNECT_BASE_S    — float (default: 1.0)
    WS_RECONNECT_MAX_S     — float (default: 60.0)
    GAMMA_API_URL          — Gamma REST base URL (default: https://gamma-api.polymarket.com)
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import structlog

log = structlog.get_logger()

# ── Required credentials ──────────────────────────────────────────────────────

_REQUIRED_CREDENTIALS: list[str] = [
    "CLOB_API_KEY",
    "CLOB_API_SECRET",
    "CLOB_API_PASSPHRASE",
]

_REQUIRED_TELEGRAM: list[str] = [
    "TELEGRAM_CHAT_ID",
]

# Telegram token may come in as either name; we accept both.
_TELEGRAM_TOKEN_ALIASES: list[str] = ["TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN"]

# ── Defaults for optional config ──────────────────────────────────────────────

_DEFAULT_MODE: str = "PAPER"
_DEFAULT_MAX_MARKETS: int = 5
_DEFAULT_MAX_CAPITAL_USD: float = 10_000.0
_DEFAULT_MAX_TRADES_PER_DAY: int = 200
_DEFAULT_DAILY_LOSS_LIMIT: float = -2_000.0
_DEFAULT_MAX_DRAWDOWN_PCT: float = 0.08
_DEFAULT_MIN_LIQUIDITY_USD: float = 10_000.0
_DEFAULT_MAX_POSITION_USD: float = 1_000.0
_DEFAULT_MAX_SLIPPAGE_PCT: float = 0.03
_DEFAULT_HEALTH_LOG_INTERVAL_S: float = 60.0
_DEFAULT_WS_HEARTBEAT_TIMEOUT_S: float = 30.0
_DEFAULT_WS_RECONNECT_BASE_S: float = 1.0
_DEFAULT_WS_RECONNECT_MAX_S: float = 60.0
_DEFAULT_CLOB_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
_DEFAULT_GAMMA_API_URL: str = "https://gamma-api.polymarket.com"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _env(name: str, default: str = "") -> str:
    """Return stripped env var value or *default*."""
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("bootstrap_parse_float_failed", env_var=name, raw=raw, default=default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("bootstrap_parse_int_failed", env_var=name, raw=raw, default=default)
        return default


def _get_telegram_token() -> str:
    """Return the Telegram bot token from either alias, or empty string."""
    for alias in _TELEGRAM_TOKEN_ALIASES:
        val = _env(alias)
        if val:
            return val
    return ""


# ── Credential validation ─────────────────────────────────────────────────────


def validate_credentials() -> None:
    """Validate that all required credentials are present.

    Raises:
        RuntimeError: With a descriptive message listing every missing credential.
    """
    missing: list[str] = []

    for name in _REQUIRED_CREDENTIALS:
        if not _env(name):
            missing.append(name)

    # Telegram token — at least one alias must be set
    if not _get_telegram_token():
        missing.append("TELEGRAM_TOKEN (or TELEGRAM_BOT_TOKEN)")

    for name in _REQUIRED_TELEGRAM:
        if not _env(name):
            missing.append(name)

    if missing:
        raise RuntimeError(
            "PolyQuantBot cannot start: the following required environment variables "
            f"are not set: {', '.join(missing)}. "
            "Set them in your .env file or deployment environment and restart."
        )

    log.info("bootstrap_credentials_valid", message="All required credentials present.")


# ── Optional config builder ───────────────────────────────────────────────────


def build_config() -> dict[str, Any]:
    """Build a complete pipeline configuration dict from environment variables.

    All optional values are filled with safe production defaults when not set.

    Returns:
        Pipeline configuration dict compatible with LivePaperRunner and
        Phase10PipelineRunner.
    """
    # MODE can be set via either 'MODE' or 'TRADING_MODE'; 'TRADING_MODE' wins.
    mode = _env("TRADING_MODE") or _env("MODE") or _DEFAULT_MODE
    mode = mode.upper()

    cfg: dict[str, Any] = {
        "websocket": {
            "url": _env("CLOB_WS_URL") or _DEFAULT_CLOB_WS_URL,
            "heartbeat_timeout_s": _env_float("WS_HEARTBEAT_TIMEOUT_S", _DEFAULT_WS_HEARTBEAT_TIMEOUT_S),
            "reconnect_base_delay_s": _env_float("WS_RECONNECT_BASE_S", _DEFAULT_WS_RECONNECT_BASE_S),
            "reconnect_max_delay_s": _env_float("WS_RECONNECT_MAX_S", _DEFAULT_WS_RECONNECT_MAX_S),
        },
        "go_live": {
            "mode": mode,
            "max_capital_usd": _env_float("MAX_CAPITAL_USD", _DEFAULT_MAX_CAPITAL_USD),
            "max_trades_per_day": _env_int("MAX_TRADES_PER_DAY", _DEFAULT_MAX_TRADES_PER_DAY),
        },
        "risk": {
            "daily_loss_limit": _env_float("DAILY_LOSS_LIMIT", _DEFAULT_DAILY_LOSS_LIMIT),
            "max_drawdown_pct": _env_float("MAX_DRAWDOWN_PCT", _DEFAULT_MAX_DRAWDOWN_PCT),
        },
        "metrics": {
            "health_log_interval_s": _env_float("HEALTH_LOG_INTERVAL_S", _DEFAULT_HEALTH_LOG_INTERVAL_S),
        },
        "execution_guard": {
            "min_liquidity_usd": _env_float("MIN_LIQUIDITY_USD", _DEFAULT_MIN_LIQUIDITY_USD),
            "max_slippage_pct": _env_float("MAX_SLIPPAGE_PCT", _DEFAULT_MAX_SLIPPAGE_PCT),
            "max_position_usd": _env_float("MAX_POSITION_USD", _DEFAULT_MAX_POSITION_USD),
        },
    }

    log.info(
        "bootstrap_config_built",
        mode=mode,
        max_capital_usd=cfg["go_live"]["max_capital_usd"],
        daily_loss_limit=cfg["risk"]["daily_loss_limit"],
    )
    return cfg


# ── Market discovery ──────────────────────────────────────────────────────────


def _parse_market_ids_from_env() -> list[str]:
    """Return market IDs explicitly set via MARKET_IDS env var.

    Returns empty list when MARKET_IDS is unset, empty, or set to "auto"
    (all of which trigger automatic Gamma API market discovery).
    """
    raw = _env("MARKET_IDS")
    if not raw or raw.lower() == "auto":
        return []
    return [mid.strip() for mid in raw.split(",") if mid.strip()]


async def _fetch_active_markets(
    gamma_url: str,
    min_liquidity: float,
    max_markets: int,
) -> list[str]:
    """Fetch active markets from the Gamma REST API.

    Selects markets that are:
      - active (active == True)
      - have volume >= min_liquidity

    Returns the top *max_markets* condition IDs sorted by volume descending.

    Args:
        gamma_url: Gamma API base URL.
        min_liquidity: Minimum USD volume threshold.
        max_markets: Maximum number of markets to return.

    Returns:
        List of condition IDs (may be empty if none qualify).

    Raises:
        RuntimeError: On network / HTTP errors so the caller can hard-fail.
    """
    try:
        import aiohttp  # optional dependency
    except ImportError as exc:
        raise RuntimeError(
            "aiohttp is required for automatic market discovery. "
            "Install it with: pip install aiohttp"
        ) from exc

    url = f"{gamma_url.rstrip('/')}/markets"
    params: dict[str, Any] = {
        "active": "true",
        "closed": "false",
        "limit": 100,
    }

    log.info("bootstrap_market_discovery_start", url=url, min_liquidity=min_liquidity)

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"Gamma API returned HTTP {resp.status} while fetching markets."
                )
            data = await resp.json()

    # Gamma returns a list or a dict with a 'markets' key — handle both shapes.
    if isinstance(data, dict):
        markets: list[dict] = data.get("markets", [])
    elif isinstance(data, list):
        markets = data
    else:
        markets = []

    # Filter by liquidity (volume field names vary across API versions).
    qualifying: list[dict] = []
    for m in markets:
        vol = float(
            m.get("volume", 0)
            or m.get("volumeNum", 0)
            or m.get("liquidity", 0)
            or 0
        )
        if vol >= min_liquidity:
            qualifying.append({**m, "_vol": vol})

    # Sort descending by volume and take top N.
    qualifying.sort(key=lambda x: x["_vol"], reverse=True)
    top = qualifying[:max_markets]

    # Store rich market metadata for /markets display
    market_meta = []
    for m in top:
        outcomes = m.get("outcomes", [])
        tokens = m.get("tokens", [])
        # Parse YES price from outcomePrices or tokens
        yes_price = None
        no_price = None
        outcome_prices = m.get("outcomePrices", [])
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                yes_price = round(float(outcome_prices[0]), 3)
                no_price = round(float(outcome_prices[1]), 3)
            except (ValueError, TypeError):
                pass
        elif tokens:
            for t in tokens:
                outcome = (t.get("outcome") or "").lower()
                price = t.get("price") or t.get("lastPrice")
                if price:
                    try:
                        if "yes" in outcome:
                            yes_price = round(float(price), 3)
                        elif "no" in outcome:
                            no_price = round(float(price), 3)
                    except (ValueError, TypeError):
                        pass
        market_meta.append({
            "conditionId": m.get("conditionId", ""),
            "question": m.get("question") or m.get("title") or m.get("description", "Unknown"),
            "volume": m.get("_vol", 0),
            "yes_price": yes_price,
            "no_price": no_price,
            "end_date": (m.get("endDate") or m.get("end_date_iso") or "")[:10],
        })

    for m in top:
        # Prefer clobTokenIds (flat list of YES/NO token IDs) for WS subscription
        clob_tokens = m.get("clobTokenIds") or []
        if isinstance(clob_tokens, list) and clob_tokens:
            token_ids.extend(str(t) for t in clob_tokens if t)
        elif m.get("tokens"):
            for t in m["tokens"]:
                tid = t.get("token_id") or t.get("tokenId") or t.get("id")
                if tid:
                    token_ids.append(str(tid))

        cid = m.get("conditionId")
        if cid:
            condition_ids.append(cid)

    # Use token_ids for WS subscription; fall back to condition_ids if unavailable
    ws_ids = token_ids if token_ids else condition_ids

    log.info(
        "bootstrap_market_discovery_complete",
        total_fetched=len(markets),
        qualifying=len(qualifying),
        selected=len(condition_ids),
        token_ids_count=len(token_ids),
        using_token_ids=bool(token_ids),
        ws_ids_sample=ws_ids[:3],
        condition_ids=condition_ids,
    )
    return ws_ids, market_meta


async def discover_markets(cfg: dict[str, Any]) -> tuple[list[str], list[dict]]:
    """Return market IDs + metadata. Auto-discovers via Gamma API if MARKET_IDS not set."""
    explicit = _parse_market_ids_from_env()
    if explicit:
        log.info("bootstrap_using_explicit_market_ids", count=len(explicit))
        return explicit, []

    max_markets = _env_int("MAX_MARKETS", _DEFAULT_MAX_MARKETS)
    min_liquidity = cfg.get("execution_guard", {}).get(
        "min_liquidity_usd", _DEFAULT_MIN_LIQUIDITY_USD
    )
    gamma_url = _env("GAMMA_API_URL") or _DEFAULT_GAMMA_API_URL

    market_ids, market_meta = await _fetch_active_markets(
        gamma_url=gamma_url,
        min_liquidity=min_liquidity,
        max_markets=max_markets,
    )

    if not market_ids:
        raise RuntimeError(
            "Market discovery returned zero qualifying markets "
            f"(min_liquidity_usd={min_liquidity}, max_markets={max_markets}). "
            "Either set MARKET_IDS explicitly or lower MIN_LIQUIDITY_USD."
        )

    return market_ids, market_meta


# ── Startup log ───────────────────────────────────────────────────────────────


def log_startup(mode: str, market_ids: list[str]) -> None:
    """Emit a structured startup-ready log entry.

    Args:
        mode: Trading mode string (PAPER or LIVE).
        market_ids: Markets selected for the session.
    """
    log.info(
        "bootstrap_system_ready",
        mode=mode,
        markets_selected=len(market_ids),
        market_ids=market_ids,
        message=(
            f"✅ PolyQuantBot ready — mode={mode}, "
            f"markets={len(market_ids)} ({', '.join(market_ids[:3])}"
            + (", ..." if len(market_ids) > 3 else "")
            + ")"
        ),
    )


# ── Public entry point ────────────────────────────────────────────────────────


async def run_bootstrap() -> tuple[dict[str, Any], list[str]]:
    """Run the full production bootstrap sequence.

    Steps:
      1. Validate required credentials (hard fail on missing).
      2. Build pipeline config with defaults for optional values.
      3. Discover markets (from env or Gamma API).
      4. Emit startup log.

    Returns:
        Tuple of (cfg, market_ids) where:
          - cfg is the pipeline configuration dict.
          - market_ids is a non-empty list of condition IDs.

    Raises:
        RuntimeError: For missing credentials or empty market discovery.
    """
    validate_credentials()
    cfg = build_config()
    market_ids, market_meta = await discover_markets(cfg)
    mode = cfg["go_live"]["mode"]
    log_startup(mode, market_ids)
    return cfg, market_ids, market_meta
