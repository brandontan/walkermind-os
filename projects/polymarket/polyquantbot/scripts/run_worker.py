"""CrusaderBot — Trading pipeline worker runner.

Starts the core trading pipeline (market discovery + signal + execution loop)
independently of the HTTP control-plane.
Intended for Fly.io process model separation or standalone worker operation.

Usage:
    python scripts/run_worker.py

Required environment variables:
    DB_DSN          — PostgreSQL connection DSN
    TRADING_MODE    — PAPER | LIVE (default: PAPER)

Optional:
    MARKET_IDS       — Comma-separated Polymarket condition IDs, or "auto"
    REDIS_URL        — Redis connection URL
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — for alert notifications
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import structlog

log = structlog.get_logger(__name__)

_REQUIRED_ENV: list[str] = ["DB_DSN"]


def _validate_env() -> None:
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        log.error(
            "crusaderbot_worker_startup_blocked",
            missing_env=missing,
            hint="Set DB_DSN before starting the pipeline worker",
        )
        print(
            f"[CrusaderBot Worker] STARTUP BLOCKED — missing: {missing}",
            file=sys.stderr,
        )
        sys.exit(1)


async def _run() -> None:
    _validate_env()

    print("🛡️ CrusaderBot pipeline worker starting")
    log.info("crusaderbot_worker_starting", app="CrusaderBot")

    from projects.polymarket.polyquantbot.core.bootstrap import run_bootstrap

    cfg, market_ids, market_meta = await run_bootstrap()
    log.info(
        "crusaderbot_worker_bootstrap_complete",
        app="CrusaderBot",
        market_count=len(market_ids),
    )

    from projects.polymarket.polyquantbot.core.pipeline.live_paper_runner import LivePaperRunner

    runner = LivePaperRunner.from_config(cfg=cfg, market_ids=market_ids)
    await runner.start()

    stop_event = asyncio.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        log.info("crusaderbot_worker_shutdown_signal", signum=signum)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_signal)
        except (OSError, ValueError):
            pass

    pipeline_task = asyncio.create_task(runner.run(), name="trading_pipeline")
    log.info(
        "crusaderbot_worker_running",
        app="CrusaderBot",
        mode=os.environ.get("TRADING_MODE", "PAPER"),
        market_count=len(market_ids),
    )

    await stop_event.wait()

    log.info("crusaderbot_worker_shutting_down")
    pipeline_task.cancel()
    try:
        await pipeline_task
    except asyncio.CancelledError:
        pass
    await runner.stop()
    log.info("crusaderbot_worker_stopped", app="CrusaderBot")


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("crusaderbot_worker_keyboard_interrupt")
    except Exception as exc:
        log.error("crusaderbot_worker_fatal", error=str(exc), exc_info=True)
        sys.exit(1)
