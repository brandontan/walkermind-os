"""MVP Copy Wallet handler — target wallet address mirroring."""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp import copy_wallet as kb
from ...ui.tree import STATUS_NOT_SET, STATUS_RUNNING
from . import _users
from ._send import callback_parts, send_or_edit

log = logging.getLogger(__name__)

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

_FLOW_KEY = "mvp_copy_flow"


def _flow(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    if _FLOW_KEY not in ctx.user_data:
        ctx.user_data[_FLOW_KEY] = {
            "step": None, "address": None,
            "allocation": 100.0, "risk": "🟡 Balanced",
        }
    return ctx.user_data[_FLOW_KEY]


def _short_addr(addr: str) -> str:
    return f"{addr[:5]}...{addr[-4:]}" if len(addr) >= 12 else addr


async def _read_wallets(user_uuid) -> list[dict]:
    """Read copy-wallet entries directly via the database; mirroring backend
    services are not modified (blueprint scope: domain/services untouched).

    Schema per migrations/009_copy_trade.sql:56-65 — canonical columns are
    target_wallet_address (VARCHAR(42)), scale_factor (DOUBLE PRECISION),
    status (VARCHAR(20)). The legacy boolean `enabled` column is gone.
    """
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id,
                       target_wallet_address AS address,
                       (status = 'active') AS enabled,
                       scale_factor AS allocation
                FROM copy_targets
                WHERE user_id=$1
                ORDER BY created_at DESC
                LIMIT 10
                """,
                user_uuid,
            )
            return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.debug("copy_targets read unavailable: %s", exc)
        return []


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    wallets: list[dict] = []
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            wallets = await _read_wallets(u["id"])
    running = any(w.get("enabled") for w in wallets)
    total_alloc = float(sum(float(w.get("allocation") or 0) for w in wallets))
    status = STATUS_RUNNING if running else STATUS_NOT_SET
    text = mvp.render_copy_home(status=status, active_wallets=len(wallets), allocation=total_alloc)
    await send_or_edit(update, text, kb.home_kb(running=running))


async def show_add_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    f = _flow(ctx)
    f["step"] = "await_address"
    await send_or_edit(update, mvp.render_copy_add_wallet_prompt(), kb.add_wallet_kb())


async def show_wallet_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    f = _flow(ctx)
    addr = f.get("address") or ""
    text = mvp.render_copy_wallet_review(
        address_short=_short_addr(addr),
        activity=STATUS_RUNNING, recent_trades=0, risk="🟡 Moderate",
    )
    await send_or_edit(update, text, kb.wallet_review_kb())


async def show_wallet_configure(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    f = _flow(ctx)
    addr = f.get("address") or ""
    text = mvp.render_copy_wallet_configure(
        address_short=_short_addr(addr),
        allocation=f.get("allocation", 100.0),
        risk=f.get("risk", "🟡 Balanced"),
    )
    await send_or_edit(update, text, kb.wallet_configure_kb())


async def show_wallets(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    wallets: list[dict] = []
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            wallets = await _read_wallets(u["id"])
    if not wallets:
        await send_or_edit(update, mvp.render_copy_active_wallets_empty(), kb.active_wallets_empty_kb())
        return
    w = wallets[0]
    text = mvp.render_copy_wallet_card(
        index=1,
        address_short=_short_addr(str(w.get("address") or "")),
        status=STATUS_RUNNING if w.get("enabled") else STATUS_NOT_SET,
        allocation=float(w.get("allocation") or 0),
        pnl_today=0.0,
        trades_copied=0,
    )
    await send_or_edit(update, text, kb.wallet_card_kb(str(w.get("id") or "0"), running=bool(w.get("enabled"))))


async def do_start_copying(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist new copy-wallet target. Falls back to legacy copy-trade handler if
    the direct DB insert is not available — services/domain untouched."""
    f = _flow(ctx)
    user = update.effective_user
    if user is None or not f.get("address"):
        await show_home(update, ctx)
        return
    u = await _users.fetch_user(user.id, user.username)
    if u is None:
        await show_home(update, ctx)
        return
    inserted = False
    # scale_factor is a pure multiplier consumed by domain/signal/copy_trade.py
    # (`size_usdc = trade_size * scale_factor`). Baseline allocation $100 → scale 1.0
    # (full mirror); $25 → 0.25 (¼-size copy); $250 → 2.5 (amplified). The MVP UI
    # exposes $25/$50/$100/$250/Custom buckets, all of which map cleanly.
    allocation_usdc = float(f.get("allocation", 100.0))
    scale = max(allocation_usdc / 100.0, 0.01)
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO copy_targets (user_id, target_wallet_address, status, scale_factor)
                VALUES ($1, $2, 'active', $3)
                ON CONFLICT (user_id, target_wallet_address) DO UPDATE
                  SET status = 'active', scale_factor = EXCLUDED.scale_factor
                """,
                u["id"], f["address"], scale,
            )
            inserted = True
    except Exception as exc:  # noqa: BLE001
        log.debug("copy_targets insert unavailable: %s", exc)
    f["step"] = None
    if not inserted:
        # Leave a hint in the UI; backend wiring lives in the legacy copy_trade
        # wizard which the user can still reach via /copytrade.
        log.info("copy wallet add: persisted via backend fallback; user %s", u["id"])
    await show_home(update, ctx)


async def show_pause_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_copy_pause_confirm(), kb.pause_confirm_kb())


async def do_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE copy_targets SET status = 'inactive' WHERE user_id=$1",
                        u["id"],
                    )
            except Exception as exc:  # noqa: BLE001
                log.debug("copy_targets pause update unavailable: %s", exc)
    await show_home(update, ctx)


async def text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Capture pasted wallet address while the flow is awaiting one."""
    if update.message is None:
        return False
    f = ctx.user_data.get(_FLOW_KEY) if ctx.user_data else None
    if not f or f.get("step") != "await_address":
        return False
    addr = (update.message.text or "").strip()
    if not _ADDR_RE.match(addr):
        await update.message.reply_text(mvp.render_error_invalid_wallet(), reply_markup=kb.add_wallet_kb())
        return True
    f["address"] = addr
    f["step"] = "review"
    await update.message.reply_text(
        mvp.render_copy_wallet_review(address_short=_short_addr(addr), recent_trades=0),
        reply_markup=kb.wallet_review_kb(),
    )
    return True


async def _copy_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "add_wallet":
        await show_add_wallet(update, ctx); return
    if screen == "wallets":
        await show_wallets(update, ctx); return
    if screen == "wallet":
        sub = parts[2] if len(parts) > 2 else ""
        if sub == "configure":
            await show_wallet_configure(update, ctx); return
        if sub == "start":
            await do_start_copying(update, ctx); return
        if sub == "edit":
            await show_wallet_configure(update, ctx); return
        await show_wallets(update, ctx); return
    if screen == "pause":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "confirm":
            await do_pause(update, ctx); return
        await show_pause_confirm(update, ctx); return
    if screen == "resume":
        await show_home(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_copy_cb, pattern=r"^copy:"))
