"""PolyQuantBot — main entrypoint.

Bootstraps the PolyQuantBot pipeline from environment variables and starts
the LivePaperRunner (PAPER mode) or Phase10PipelineRunner (LIVE mode) based
on the TRADING_MODE / MODE env var.

Bootstrap sequence (handled by core.bootstrap):
  1. Validate required credentials — hard fail if missing.
  2. Build pipeline config with safe defaults for optional values.
  3. Discover markets: MARKET_IDS env var takes priority; otherwise the
     Gamma REST API is queried for the top-N active, liquid markets.
  4. Emit structured startup log.

Required environment variables:
    CLOB_API_KEY
    CLOB_API_SECRET
    CLOB_API_PASSPHRASE
    TELEGRAM_TOKEN   (alias: TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID

Optional environment variables (with defaults):
    TRADING_MODE / MODE     PAPER | LIVE  (default: PAPER)
    MARKET_IDS              comma-separated condition IDs (disables auto-discovery)
    ENABLE_LIVE_TRADING     true | false  (must be "true" to unlock LIVE mode)
    MAX_MARKETS             int  (default: 5)
    CLOB_WS_URL             WebSocket URL override
    MAX_CAPITAL_USD         float (default: 10000)
    DAILY_LOSS_LIMIT        float (default: -2000)
    MAX_DRAWDOWN_PCT        float (default: 0.08)
    MIN_LIQUIDITY_USD       float (default: 10000)
    REDIS_URL               Redis connection URL
    DB_DSN                  PostgreSQL DSN

Usage::

    python -m projects.polymarket.polyquantbot.main
    # or via root entrypoint:
    python main.py
"""
from __future__ import annotations

import asyncio
import os
import sys

import structlog

log = structlog.get_logger()


async def main() -> None:
    """Bootstrap and run the PolyQuantBot trading pipeline."""
    log.info("polyquantbot_starting", message="🚀 PolyQuantBot starting")

    # ── Bootstrap: validate credentials, build config, discover markets ──────
    from projects.polymarket.polyquantbot.core.bootstrap import run_bootstrap

    try:
        cfg, market_ids = await run_bootstrap()
    except RuntimeError as exc:
        log.error("bootstrap_failed", error=str(exc))
        sys.exit(1)

    trading_mode: str = cfg["go_live"]["mode"]

    # ── Extra LIVE guard: ENABLE_LIVE_TRADING must be explicitly true ─────────
    if trading_mode == "LIVE":
        enable_live = os.getenv("ENABLE_LIVE_TRADING", "false").strip().lower()
        if enable_live != "true":
            log.error(
                "live_trading_disabled",
                message="ENABLE_LIVE_TRADING is not 'true'; refusing to start in LIVE mode.",
            )
            sys.exit(1)

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
