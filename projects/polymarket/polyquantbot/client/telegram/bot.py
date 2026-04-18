"""CrusaderBot — Telegram client bootstrap.

Thin entry surface for the Telegram polling client.
Delegates to the existing telegram/ module for all handler logic.

This file is the structural anchor for the Crusader multi-user blueprint.
Full polling orchestration lives in the main pipeline until the client/server
split is complete.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    _repo_root = Path(__file__).resolve().parents[5]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

import structlog

log = structlog.get_logger(__name__)

CRUSADERBOT_NAME = "CrusaderBot"


async def start_telegram_client() -> object:
    """Bootstrap Telegram client for CrusaderBot.

    Returns the TelegramLive instance (started).
    Caller is responsible for lifecycle management.
    """
    log.info("crusaderbot_telegram_starting", app=CRUSADERBOT_NAME)
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive

    tg = TelegramLive.from_env()
    await tg.start()
    log.info(
        "crusaderbot_telegram_started",
        app=CRUSADERBOT_NAME,
        enabled=tg.enabled,
    )
    return tg


async def stop_telegram_client(tg: Optional[object]) -> None:
    """Gracefully stop the Telegram client."""
    if tg is None:
        return
    try:
        await tg.stop()  # type: ignore[attr-defined]
        log.info("crusaderbot_telegram_stopped", app=CRUSADERBOT_NAME)
    except Exception as exc:
        log.warning("crusaderbot_telegram_stop_error", error=str(exc))


if __name__ == "__main__":
    asyncio.run(start_telegram_client())
