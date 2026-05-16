"""Entry point: FastAPI + Telegram (polling OR webhook) + APScheduler in one process."""
from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, Response
from telegram import Update
from telegram.ext import Application

from pathlib import Path

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import notifications
from .api import admin as api_admin, health as api_health, ops as api_ops
from .webtrader.backend import sse as webtrader_sse
from .webtrader.backend.router import router as web_router
from .bot.dispatcher import register as register_handlers
from .cache import close_cache, get_cache, init_cache, set_cache
from .config import get_settings, validate_required_env
from .database import close_pool, init_pool, run_migrations
from .domain.strategy import bootstrap_default_strategies
from .monitoring import alerts as monitoring_alerts
from .monitoring import sentry as monitoring_sentry
from .monitoring.health import run_health_checks
from .monitoring.logging import RequestLogMiddleware, configure_json_logging
from .scheduler import setup_scheduler

# ----- structured logging (JSON baseline) -----
configure_json_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("crusaderbot")

bot_app: Application | None = None
scheduler_app = None

# Set to the active webhook secret only when webhook mode is running.
# Remains None in polling mode — the endpoint rejects all requests in that case.
_webhook_secret: str | None = None
_webhook_mode_active: bool = False

_STARTUP_DEDUP_KEY = "startup_notif_sent"
_STARTUP_DEDUP_TTL = 60  # seconds — covers Fly.io rolling deploy overlap


@asynccontextmanager
async def lifespan(_: FastAPI):
    global bot_app, scheduler_app, _webhook_secret, _webhook_mode_active
    # Initialise Sentry first so any subsequent boot-time exception is
    # captured. No-op when SENTRY_DSN is unset (local / CI). Failure to
    # init must not block FastAPI startup — handled inside the helper.
    monitoring_sentry.init_sentry()

    # Log missing REQUIRED env vars (key names only — values never logged) so
    # that the operator can correlate /health "down" / "degraded" states with
    # configuration drift. Boot continues; surfacing happens via /health.
    missing_env = validate_required_env()
    settings = get_settings()
    log.info(
        "CrusaderBot starting (env=%s, live_trading_enabled=%s, "
        "execution_path_validated=%s, capital_mode_confirmed=%s)",
        settings.APP_ENV,
        settings.ENABLE_LIVE_TRADING,
        settings.EXECUTION_PATH_VALIDATED,
        settings.CAPITAL_MODE_CONFIRMED,
    )

    pool = await init_pool()
    await run_migrations()
    await init_cache()
    bootstrap_default_strategies()
    await webtrader_sse.start_listener(settings.DATABASE_URL, pool)

    use_webhook = bool(settings.TELEGRAM_WEBHOOK_URL)

    builder = Application.builder().token(settings.TELEGRAM_BOT_TOKEN)
    if use_webhook:
        # Disable the built-in updater so PTB does not start its own polling
        # loop; we drive updates manually via the /telegram/webhook route.
        builder = builder.updater(None)

    bot_app = builder.build()
    register_handlers(bot_app)
    notifications.set_bot(bot_app.bot)

    await bot_app.initialize()
    await bot_app.start()

    if use_webhook:
        # Always enforce secret validation in webhook mode.
        # Generate one at runtime only if the operator hasn't set one explicitly.
        # The generated value is NOT logged (it is a secret); set
        # TELEGRAM_WEBHOOK_SECRET explicitly so it survives restarts.
        secret = settings.TELEGRAM_WEBHOOK_SECRET or secrets.token_hex(32)
        if not settings.TELEGRAM_WEBHOOK_SECRET:
            log.warning(
                "TELEGRAM_WEBHOOK_SECRET is not set — using an ephemeral secret. "
                "Set this env var explicitly so it survives restarts."
            )

        await bot_app.bot.set_webhook(
            url=settings.TELEGRAM_WEBHOOK_URL,
            secret_token=secret,
            allowed_updates=Update.ALL_TYPES,
        )
        # Only activate the endpoint after the webhook is registered and secret is ready.
        _webhook_secret = secret
        _webhook_mode_active = True
        log.info("Telegram webhook registered: %s", settings.TELEGRAM_WEBHOOK_URL)
    else:
        if bot_app.updater:
            await bot_app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram polling started.")

    scheduler_app = setup_scheduler()
    scheduler_app.start()
    log.info("Scheduler started with %d jobs.", len(scheduler_app.get_jobs()))

    all_guards_ready = (
        settings.ENABLE_LIVE_TRADING
        and settings.EXECUTION_PATH_VALIDATED
        and settings.CAPITAL_MODE_CONFIRMED
    )

    # Persist a timestamped audit record whenever all three operator guards are
    # enabled at startup. This creates an append-only DB proof that the operator
    # consciously activated live-trading gates — queryable via audit.log.
    if all_guards_ready:
        from . import audit as _audit
        await _audit.write(
            actor_role="operator",
            action="live_gate_opened",
            payload={
                "ENABLE_LIVE_TRADING": settings.ENABLE_LIVE_TRADING,
                "EXECUTION_PATH_VALIDATED": settings.EXECUTION_PATH_VALIDATED,
                "CAPITAL_MODE_CONFIRMED": settings.CAPITAL_MODE_CONFIRMED,
                "APP_ENV": settings.APP_ENV,
                "note": (
                    "All three activation guards are True at startup. "
                    "Tier 4 users who have switched to live mode will now "
                    "route real orders to the Polymarket CLOB."
                ),
            },
        )
        log.info("live_gate_opened audit event written (all activation guards enabled)")

    # Operator-only boot alert — must NEVER target a regular user's chat_id.
    # Guard ensures the send is skipped rather than misdirected when
    # OPERATOR_CHAT_ID is not yet configured.
    # 60-second Redis dedup prevents duplicate alerts during Fly.io rolling
    # deploys where old and new instances overlap briefly.
    if settings.OPERATOR_CHAT_ID:
        _notif_suppressed = False
        try:
            _notif_suppressed = bool(await get_cache(_STARTUP_DEDUP_KEY))
        except Exception as exc:
            log.warning("startup dedup cache check failed — proceeding: %s", exc)
        if _notif_suppressed:
            log.info("startup notification suppressed (duplicate within 60s)")
        else:
            try:
                await set_cache(_STARTUP_DEDUP_KEY, "1", ttl=_STARTUP_DEDUP_TTL)
            except Exception as exc:
                log.warning("startup dedup cache set failed: %s", exc)
            await notifications.send(
                settings.OPERATOR_CHAT_ID,
                f"🟢 CrusaderBot up\nenv: {settings.APP_ENV}\n"
                f"mode: {'webhook' if use_webhook else 'polling'}\n"
                f"live_trading_enabled: {settings.ENABLE_LIVE_TRADING}\n"
                f"execution_path_validated: {settings.EXECUTION_PATH_VALIDATED}\n"
                f"capital_mode_confirmed: {settings.CAPITAL_MODE_CONFIRMED}\n"
                f"{'✅ activation guards OPEN — live trading enabled' if all_guards_ready else '🔒 activation guards LOCKED — all trades route to paper'}",
                parse_mode=None,
            )

    # --- observability: startup alert + dependency probe ---
    # Fly.io starts a fresh machine on every deploy or VM restart, so a boot
    # event always counts as a machine restart from the operator's POV.
    # Alert delivery is fire-and-forget so a slow Telegram cannot stall
    # app.startup past Fly's 10s grace_period and trigger a restart loop.
    # run_health_checks() is bounded by its own per-check 3s timeout, so
    # awaiting it here is safe.
    try:
        if missing_env:
            # One aggregated page covers all missing keys; per-variable
            # alerts would collide on the same cooldown bucket and silently
            # drop every key after the first.
            monitoring_alerts.schedule_alert(
                monitoring_alerts.alert_missing_env(missing_env),
            )
        boot_health = await run_health_checks()
        if boot_health["status"] != "ok":
            for name, reason in boot_health["checks"].items():
                if reason != "ok":
                    monitoring_alerts.schedule_alert(
                        monitoring_alerts.alert_dependency_unreachable(name, reason),
                    )
    except Exception as exc:  # noqa: BLE001 — observability must never crash boot
        log.error("startup observability hook failed: %s", exc, exc_info=True)

    try:
        yield
    finally:
        log.info("CrusaderBot shutting down…")
        # Deactivate the endpoint before tearing down the bot.
        _webhook_mode_active = False
        _webhook_secret = None
        try:
            if use_webhook and bot_app:
                await bot_app.bot.delete_webhook()
        except Exception as exc:
            log.warning("delete_webhook error: %s", exc)
        try:
            if scheduler_app:
                scheduler_app.shutdown(wait=False)
        except Exception as exc:
            log.warning("scheduler shutdown error: %s", exc)
        try:
            from .scheduler import ws_shutdown
            await ws_shutdown()
        except Exception as exc:
            log.warning("ws shutdown error: %s", exc)
        try:
            if bot_app and bot_app.updater:
                await bot_app.updater.stop()
        except Exception as exc:
            log.warning("updater stop error: %s", exc)
        try:
            if bot_app:
                await bot_app.stop()
                await bot_app.shutdown()
        except Exception as exc:
            log.warning("bot shutdown error: %s", exc)
        await webtrader_sse.stop_listener()
        await close_cache()
        await close_pool()


app = FastAPI(title="CrusaderBot", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware)
app.include_router(api_health.router)
app.include_router(api_admin.router)
app.include_router(api_ops.router)
app.include_router(web_router, prefix="/api/web")

# Serve the React frontend from /dashboard (static files from the Docker build)
_frontend_dist = Path(__file__).parent / "webtrader" / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_frontend_dist), html=True), name="webtrader")
else:
    log.warning("WebTrader dist not found at %s — /dashboard will not serve the UI", _frontend_dist)


@app.get("/")
async def root():
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Receive Telegram update pushes when running in webhook mode.

    Returns 404 if the app is running in polling mode (webhook not configured).
    Returns 403 if the secret token header is missing or incorrect.
    Secret validation is always enforced — there is no unauthenticated path.
    """
    # Reject all requests when webhook mode is not active (e.g. polling mode).
    if not _webhook_mode_active:
        raise HTTPException(status_code=404, detail="webhook not enabled")

    # At this point _webhook_secret is always set (assigned before _webhook_mode_active
    # is flipped to True), so secret validation is unconditional.
    if x_telegram_bot_api_secret_token != _webhook_secret:
        raise HTTPException(status_code=403, detail="invalid secret token")

    if bot_app is None:
        raise HTTPException(status_code=503, detail="bot not ready")

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return Response(status_code=200)
