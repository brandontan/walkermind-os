"""Telegram dispatcher: builds Application, registers /start (onboarding) and /status."""
from __future__ import annotations

from functools import partial

import asyncpg
import structlog
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from ..config import Settings, settings
from .handlers.onboarding import handle_start

log = structlog.get_logger(__name__)


async def status_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message is None:
        return
    guards = settings.guard_states
    lines = ["Guard states:"]
    for name, value in guards.items():
        marker = "✅ ON" if value else "⚪ OFF"
        lines.append(f"- {name}: {marker}")
    mode = "LIVE" if settings.ENABLE_LIVE_TRADING else "PAPER"
    lines.append("")
    lines.append(f"Mode: {mode}")
    lines.append(f"Env: {settings.APP_ENV}")
    await update.effective_message.reply_text("\n".join(lines))


def setup_handlers(
    app: Application,
    *,
    db_pool: asyncpg.Pool,
    config: Settings,
) -> None:
    """Register handlers. db_pool and config are bound into /start via partial.

    Both kwargs are required; missing them at call time raises TypeError fast.
    """
    bound_start = partial(handle_start, pool=db_pool, config=config)
    app.add_handler(CommandHandler("start", bound_start))
    app.add_handler(CommandHandler("status", status_handler))
    log.info("bot.handlers_registered", commands=["start", "status"])


def get_application() -> Application:
    return ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
