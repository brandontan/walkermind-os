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

    db_connected = False
    cache_connected = False
    bot_app = None
    bot_started = False
    polling_started = False

    async def _unwind() -> None:
        if polling_started and bot_app is not None and bot_app.updater is not None and bot_app.updater.running:
            try:
                await bot_app.updater.stop()
            except Exception as exc:
                log.warning("shutdown.step_failed", step="updater.stop", error=str(exc))
        if bot_started and bot_app is not None:
            try:
                await bot_app.stop()
                await bot_app.shutdown()
            except Exception as exc:
                log.warning("shutdown.step_failed", step="bot.shutdown", error=str(exc))
        if cache_connected:
            try:
                await cache.disconnect()
            except Exception as exc:
                log.warning("shutdown.step_failed", step="cache.disconnect", error=str(exc))
        if db_connected:
            try:
                await db.disconnect()
            except Exception as exc:
                log.warning("shutdown.step_failed", step="db.disconnect", error=str(exc))

    try:
        await db.connect()
        db_connected = True
        await cache.connect()
        cache_connected = True
        await db.run_migrations()

        bot_app = get_application()
        setup_handlers(bot_app)
        await bot_app.initialize()
        await bot_app.start()
        bot_started = True
        await bot_app.updater.start_polling()
        polling_started = True
    except Exception as exc:
        log.error("startup.failed", error=str(exc), error_type=type(exc).__name__)
        await _unwind()
        raise

    log.info("startup.complete")

    try:
        yield
    finally:
        log.info("shutdown.begin")
        await _unwind()
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
