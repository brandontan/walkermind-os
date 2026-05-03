"""Telegram dispatcher: builds Application, registers /start and /status handlers."""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from ..config import settings

log = structlog.get_logger(__name__)


async def start_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "👋 CrusaderBot online. Paper mode active."
    )


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


def setup_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("status", status_handler))
    log.info("bot.handlers_registered", commands=["start", "status"])


def get_application() -> Application:
    return ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
