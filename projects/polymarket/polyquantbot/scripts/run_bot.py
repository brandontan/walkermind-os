"""CrusaderBot — Telegram bot standalone runner.

Starts the Telegram client independently of the trading pipeline.
Intended for Fly.io process model separation or standalone bot operation.

Usage:
    python scripts/run_bot.py

Required environment variables:
    TELEGRAM_BOT_TOKEN  — Telegram bot token
    TELEGRAM_CHAT_ID    — Default operator chat ID
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import structlog

log = structlog.get_logger(__name__)


async def _run() -> None:
    print("🛡️ CrusaderBot Telegram bot starting")
    log.info("crusaderbot_bot_runner_starting", app="CrusaderBot")

    from projects.polymarket.polyquantbot.client.telegram.bot import (
        start_telegram_client,
        stop_telegram_client,
    )

    tg = await start_telegram_client()

    stop_event = asyncio.Event()

    import signal

    def _handle_signal(signum: int, frame: object) -> None:
        log.info("crusaderbot_bot_shutdown_signal", signum=signum)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_signal)
        except (OSError, ValueError):
            pass

    log.info("crusaderbot_bot_running", app="CrusaderBot")
    await stop_event.wait()

    await stop_telegram_client(tg)
    log.info("crusaderbot_bot_stopped", app="CrusaderBot")


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("crusaderbot_bot_keyboard_interrupt")
    except Exception as exc:
        log.error("crusaderbot_bot_fatal", error=str(exc), exc_info=True)
        sys.exit(1)
