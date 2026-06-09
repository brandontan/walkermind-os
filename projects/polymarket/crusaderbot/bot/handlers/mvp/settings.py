"""MVP Settings handler — Trading Mode / Risk / Notifications / Account / Advanced."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp import settings as kb
from ...ui.tree import LIVE, PAPER
from . import _users
from ._send import callback_parts, send_or_edit

log = logging.getLogger(__name__)


async def _read_settings(telegram_user) -> dict:
    s: dict = {
        "trading_mode": PAPER,
        "daily_loss_limit": 20.0, "max_position_pct": 10,
        "max_concurrent": 3, "auto_pause_enabled": True,
        "notif_trade_opened": True, "notif_trade_closed": True,
        "notif_risk_alerts": True, "notif_daily_summary": True,
        "notif_market_alerts": False,
        "wallet_status": "Not Connected", "api_status": "🟢 Healthy",
        "subscription": "MVP", "debug_enabled": False,
        "copy_wallet_active": False, "risk_profile": "Balanced",
        "alerts_on": True,
    }
    if telegram_user is None:
        return s
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return s
    mode_raw = await _users.fetch_trading_mode(u["id"])
    s["trading_mode"] = LIVE if mode_raw == "live" else PAPER
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT risk_profile, notifications_on,
                       daily_loss_limit_usd, max_position_pct,
                       max_concurrent_trades, auto_pause_enabled
                FROM user_settings WHERE user_id=$1
                """,
                u["id"],
            )
            if row:
                s["risk_profile"] = str(row["risk_profile"] or "balanced").title()
                s["alerts_on"] = bool(row["notifications_on"] if row["notifications_on"] is not None else True)
                s["notif_trade_opened"] = s["alerts_on"]
                s["notif_trade_closed"] = s["alerts_on"]
                s["notif_risk_alerts"] = s["alerts_on"]
                s["notif_daily_summary"] = s["alerts_on"]
                if row["daily_loss_limit_usd"] is not None:
                    s["daily_loss_limit"] = float(row["daily_loss_limit_usd"])
                if row["max_position_pct"] is not None:
                    s["max_position_pct"] = int(row["max_position_pct"])
                if row["max_concurrent_trades"] is not None:
                    s["max_concurrent"] = int(row["max_concurrent_trades"])
                if row["auto_pause_enabled"] is not None:
                    s["auto_pause_enabled"] = bool(row["auto_pause_enabled"])
            # Wallet status
            wallet_addr = await conn.fetchval(
                "SELECT deposit_address FROM wallets WHERE user_id=$1", u["id"]
            )
            s["wallet_status"] = "Connected" if wallet_addr else "Not Connected"
            # Copy wallet active
            copy_active = await conn.fetchval(
                "SELECT 1 FROM copy_trade_tasks WHERE user_id=$1 AND status='active' LIMIT 1",
                u["id"],
            )
            s["copy_wallet_active"] = bool(copy_active)
    except Exception as exc:  # noqa: BLE001
        log.debug("settings read failed: %s", exc)
    return s


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ._send import nav_push
    nav_push(ctx, "settings")
    s = await _read_settings(update.effective_user)
    await send_or_edit(
        update,
        mvp.render_settings_home(
            trading_mode=s["trading_mode"],
            risk_profile=s["risk_profile"],
            alerts_on=s["alerts_on"],
            copy_wallet_active=s["copy_wallet_active"],
        ),
        kb.home_kb(),
    )


async def show_trading_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(update, mvp.render_settings_trading_mode(current=s["trading_mode"]), kb.trading_mode_kb())


async def show_live_gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Live mode is locked at the UX layer per blueprint 23.2 — UI surface only.

    Execution guard (`ENABLE_LIVE_TRADING`) is untouched; this screen never
    flips it. Activation flows route to existing live_gate handler.
    """
    await send_or_edit(update, mvp.render_settings_live_gate(), kb.live_gate_kb())


async def show_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(
        update,
        mvp.render_settings_risk_controls(
            daily_loss_limit=s["daily_loss_limit"],
            max_position_pct=s["max_position_pct"],
            max_concurrent=s["max_concurrent"],
            auto_pause_enabled=s["auto_pause_enabled"],
        ),
        kb.risk_controls_kb(),
    )


async def show_notifications(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(
        update,
        mvp.render_settings_notifications(
            trade_opened=s["notif_trade_opened"],
            trade_closed=s["notif_trade_closed"],
            risk_alerts=s["notif_risk_alerts"],
            daily_summary=s["notif_daily_summary"],
            market_alerts=s["notif_market_alerts"],
        ),
        kb.notifications_kb(),
    )


async def show_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(
        update,
        mvp.render_settings_account(
            wallet_status=s["wallet_status"],
            mode=s["trading_mode"],
            api_status=s["api_status"],
            subscription=s["subscription"],
        ),
        kb.account_kb(),
    )


async def show_advanced(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = await _read_settings(update.effective_user)
    await send_or_edit(update, mvp.render_settings_advanced(debug_enabled=s["debug_enabled"]), kb.advanced_kb())


async def _request_live_access(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Log a live-access request and confirm to the user."""
    user = update.effective_user
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO live_access_requests (user_id, requested_at)
                        VALUES ($1, NOW())
                        ON CONFLICT (user_id) DO UPDATE SET requested_at = NOW()
                        """,
                        u["id"],
                    )
            except Exception as exc:  # noqa: BLE001
                log.debug("live access request insert failed: %s", exc)
    await send_or_edit(
        update,
        mvp.render_settings_live_access_requested(),
        kb.live_gate_kb(),
    )


async def _toggle_notifications(update: Update, ctx: ContextTypes.DEFAULT_TYPE, flag: str) -> None:
    """Toggle a single notification flag in user_settings."""
    user = update.effective_user
    if user is None:
        await show_notifications(update, ctx); return
    u = await _users.fetch_user(user.id, user.username)
    if u is None:
        await show_notifications(update, ctx); return
    # All notification flags map to the single notifications_on column for now.
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            current = await conn.fetchval(
                "SELECT notifications_on FROM user_settings WHERE user_id=$1", u["id"]
            )
            new_val = not bool(current if current is not None else True)
            await conn.execute(
                "UPDATE user_settings SET notifications_on=$1, updated_at=NOW() WHERE user_id=$2",
                new_val, u["id"],
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("notifications toggle failed: %s", exc)
    await show_notifications(update, ctx)


async def _settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "mode":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "live":
            arg = parts[3] if len(parts) > 3 else None
            if arg == "request":
                await _request_live_access(update, ctx); return
            await show_live_gate(update, ctx); return
        if sub == "paper":
            await show_trading_mode(update, ctx); return
        await show_trading_mode(update, ctx); return
    if screen == "risk":
        sub = parts[2] if len(parts) > 2 else None
        # Sub-items are display-only for now — show the risk screen with current values
        await show_risk(update, ctx); return
    if screen == "notifications":
        sub = parts[2] if len(parts) > 2 else None
        if sub in {"trades", "risk", "summary", "quiet"}:
            await _toggle_notifications(update, ctx, sub); return
        await show_notifications(update, ctx); return
    if screen == "account":
        sub = parts[2] if len(parts) > 2 else None
        # wallet / export / security — show account screen (write flows deferred)
        await show_account(update, ctx); return
    if screen == "advanced":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "health":
            from ...handlers.health import health_command  # type: ignore
            await health_command(update, ctx); return
        await show_advanced(update, ctx); return
    if screen == "copy_wallet":
        from . import copy_wallet as cw
        await cw.show_home(update, ctx); return
    # Sub-routes the MVP settings surface doesn't own (tpsl / wallet / health /
    # admin / redeem_set / profile / referrals / capital / live_gate / back …)
    # were silently bounced to the MVP home; delegate them to the legacy
    # settings handler so TP/SL, wallet, health, admin etc. work from /settings.
    from .. import settings as legacy_settings
    await legacy_settings.settings_callback(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_settings_cb, pattern=r"^settings:"))
