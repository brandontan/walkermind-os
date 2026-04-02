"""PolyQuantBot — main entrypoint.

Bootstraps the PolyQuantBot pipeline from environment variables and starts
the LivePaperRunner (PAPER mode) or Phase10PipelineRunner (LIVE mode) based
on the TRADING_MODE env var.

Environment variables
---------------------
TRADING_MODE            PAPER | LIVE  (default: PAPER)
ENABLE_LIVE_TRADING     true | false  (must be "true" for LIVE mode)
MARKET_IDS              comma-separated Polymarket condition IDs to subscribe
CLOB_WS_URL             WebSocket URL  (optional override)
CLOB_API_KEY            CLOB API key   (optional)
CLOB_API_SECRET         CLOB API secret (LIVE only)
CLOB_API_PASSPHRASE     CLOB API passphrase (LIVE only)
REDIS_URL               Redis connection URL (optional)
DB_DSN                  PostgreSQL DSN (optional)
TELEGRAM_BOT_TOKEN      Telegram bot token (optional)
TELEGRAM_CHAT_ID        Telegram chat ID (optional)

Usage::

    python -m projects.polymarket.polyquantbot.main
    # or via root entrypoint:
    python main.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import List

import structlog

log = structlog.get_logger()

# ── Sentinel for missing critical env vars ────────────────────────────────────

_REQUIRED_PAPER_ENV: List[str] = []          # paper mode has no hard requirements
_REQUIRED_LIVE_ENV: List[str] = [
    "CLOB_API_KEY",
    "CLOB_API_SECRET",
    "CLOB_API_PASSPHRASE",
]


def _get_market_ids() -> List[str]:
    """Return market IDs from MARKET_IDS env var (comma-separated)."""
    raw = os.getenv("MARKET_IDS", "").strip()
    if not raw:
        return []
    return [mid.strip() for mid in raw.split(",") if mid.strip()]


def _build_config() -> dict:
    """Build a pipeline config dict from environment variables."""
    return {
        "websocket": {
            "url": os.getenv(
                "CLOB_WS_URL",
                "wss://ws-subscriptions-clob.polymarket.com/ws/market",
            ),
            "heartbeat_timeout_s": float(os.getenv("WS_HEARTBEAT_TIMEOUT_S", "30")),
            "reconnect_base_delay_s": float(os.getenv("WS_RECONNECT_BASE_S", "1.0")),
            "reconnect_max_delay_s": float(os.getenv("WS_RECONNECT_MAX_S", "60.0")),
        },
        "go_live": {
            "mode": os.getenv("TRADING_MODE", "PAPER"),
            "max_capital_usd": float(os.getenv("MAX_CAPITAL_USD", "10000")),
            "max_trades_per_day": int(os.getenv("MAX_TRADES_PER_DAY", "200")),
        },
        "risk": {
            "daily_loss_limit": float(os.getenv("DAILY_LOSS_LIMIT", "-2000")),
            "max_drawdown_pct": float(os.getenv("MAX_DRAWDOWN_PCT", "0.08")),
        },
        "metrics": {
            "health_log_interval_s": float(os.getenv("HEALTH_LOG_INTERVAL_S", "60")),
        },
        "execution_guard": {
            "min_liquidity_usd": float(os.getenv("MIN_LIQUIDITY_USD", "10000")),
            "max_slippage_pct": float(os.getenv("MAX_SLIPPAGE_PCT", "0.03")),
            "max_position_usd": float(os.getenv("MAX_POSITION_USD", "1000")),
        },
    }


def _check_env(required: List[str]) -> List[str]:
    """Return list of env var names that are missing or empty."""
    return [name for name in required if not os.getenv(name, "").strip()]


async def main() -> None:
    """Bootstrap and run the PolyQuantBot trading pipeline."""
    log.info("polyquantbot_starting", message="🚀 PolyQuantBot starting (Railway)")

    trading_mode = os.getenv("TRADING_MODE", "PAPER").strip().upper()

    # ── Validate env for LIVE mode ──────────────────────────────────────────
    if trading_mode == "LIVE":
        missing = _check_env(_REQUIRED_LIVE_ENV)
        if missing:
            log.error(
                "missing_env_vars",
                missing=missing,
                message="Required environment variables are not set; cannot start LIVE mode.",
            )
            sys.exit(1)

        enable_live = os.getenv("ENABLE_LIVE_TRADING", "false").strip().lower()
        if enable_live != "true":
            log.error(
                "live_trading_disabled",
                message="ENABLE_LIVE_TRADING is not 'true'; refusing to start in LIVE mode.",
            )
            sys.exit(1)

    market_ids = _get_market_ids()
    if not market_ids:
        log.warning(
            "no_market_ids",
            message=(
                "MARKET_IDS env var is empty. "
                "The runner will subscribe to no markets and produce no signals."
            ),
        )

    cfg = _build_config()

    log.info(
        "polyquantbot_config",
        trading_mode=trading_mode,
        market_count=len(market_ids),
    )

    if trading_mode == "LIVE":
        from projects.polymarket.polyquantbot.core.pipeline.pipeline_runner import (
            Phase10PipelineRunner,
        )

        runner = Phase10PipelineRunner.from_config(cfg, market_ids=market_ids)
        await runner.run()
    else:
        from projects.polymarket.polyquantbot.core.pipeline.live_paper_runner import (
            LivePaperRunner,
        )

        runner = LivePaperRunner.from_config(cfg, market_ids=market_ids)
        await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
