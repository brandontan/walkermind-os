"""CrusaderBot FastAPI application entrypoint.

Lifespan: connect DB → connect Redis → run migrations → start Telegram polling.
Shutdown reverses the order. Paper mode by default; live trading guarded.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI

from .api.health import router as health_router
from .bot.dispatcher import get_application, setup_handlers
from .cache import cache
from .config import settings
from .database import db


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "startup.begin",
        env=settings.APP_ENV,
        paper_mode=not settings.ENABLE_LIVE_TRADING,
        guards=settings.guard_states,
    )

    await db.connect()
    await cache.connect()
    await db.run_migrations()

    bot_app = get_application()
    setup_handlers(bot_app)
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    log.info("startup.complete")

    try:
        yield
    finally:
        log.info("shutdown.begin")
        if bot_app.updater is not None and bot_app.updater.running:
            await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        await cache.disconnect()
        await db.disconnect()
        log.info("shutdown.complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="CrusaderBot",
        version="0.1.0-r1-skeleton",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    return app


app = create_app()
