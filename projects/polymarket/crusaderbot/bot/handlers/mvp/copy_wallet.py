"""MVP Copy Wallet handler — target wallet address mirroring."""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp import copy_wallet as kb
from ...ui.tree import STATUS_NOT_SET, STATUS_RUNNING, STATUS_STOPPED
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
    """Read copy-wallet entries from the canonical execution table.

    WARP-59: MVP reads/writes use `copy_trade_tasks` so the production
    scanner (`services/copy_trade/monitor.py:run_once` → `list_active_tasks`)
    picks up wallets added via the MVP Telegram UX. Schema per
    migrations/018_copy_trade_tasks.sql + 035_copy_trade_extend.sql.
    """
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id,
                       wallet_address AS address,
                       (status = 'active') AS enabled,
                       copy_amount AS allocation
                FROM copy_trade_tasks
                WHERE user_id=$1
                ORDER BY created_at DESC
                LIMIT 10
                """,
                user_uuid,
            )
            return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.debug("copy_trade_tasks read unavailable: %s", exc)
        return []


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ._send import nav_push
    nav_push(ctx, "copy")
    user = update.effective_user
    wallets: list[dict] = []
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            wallets = await _read_wallets(u["id"])
    running = any(w.get("enabled") for w in wallets)
    total_alloc = float(sum(float(w.get("allocation") or 0) for w in wallets))
    if running:
        status = STATUS_RUNNING
    elif wallets:
        status = STATUS_STOPPED
    else:
        status = STATUS_NOT_SET
    text = mvp.render_copy_home(status=status, active_wallets=len(wallets), allocation=total_alloc)
    await send_or_edit(update, text, kb.home_kb(running=running))


async def show_add_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    f = _flow(ctx)
    f["step"] = "await_address"
    await send_or_edit(update, mvp.render_copy_add_wallet_prompt(), kb.add_wallet_kb())


async def _fetch_wallet_activity(addr: str) -> dict:
    """Fetch recent trade count for a wallet address from copy_trade_tasks history."""
    result = {"recent_trades": 0, "activity": STATUS_NOT_SET}
    if not addr:
        return result
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            # Count positions copied from this wallet in the last 7 days
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM positions p
                JOIN copy_trade_tasks t ON t.id = p.copy_task_id
                WHERE t.wallet_address=$1
                  AND p.opened_at >= NOW() - INTERVAL '7 days'
                """,
                addr.lower(),
            )
            result["recent_trades"] = int(count or 0)
            # Check if any active task exists for this wallet globally
            active = await conn.fetchval(
                "SELECT 1 FROM copy_trade_tasks WHERE wallet_address=$1 AND status='active' LIMIT 1",
                addr.lower(),
            )
            result["activity"] = STATUS_RUNNING if active else STATUS_NOT_SET
    except Exception as exc:  # noqa: BLE001
        log.debug("wallet activity fetch failed: %s", exc)
    return result


async def show_wallet_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    f = _flow(ctx)
    addr = f.get("address") or ""
    activity_data = await _fetch_wallet_activity(addr)
    text = mvp.render_copy_wallet_review(
        address_short=_short_addr(addr),
        activity=activity_data["activity"],
        recent_trades=activity_data["recent_trades"],
        risk="🟡 Moderate",
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


_WALLET_PAGE_SIZE = 1  # one wallet card per page for clarity


async def show_wallets(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int = 1
) -> None:
    user = update.effective_user
    wallets: list[dict] = []
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            wallets = await _read_wallets(u["id"])
    if not wallets:
        await send_or_edit(update, mvp.render_copy_active_wallets_empty(), kb.active_wallets_empty_kb())
        return
    total = len(wallets)
    total_pages = max(1, total)
    page = max(1, min(page, total_pages))
    if ctx.user_data is not None:
        ctx.user_data["wallets_page"] = page
    w = wallets[page - 1]
    text = mvp.render_copy_wallet_card(
        index=page,
        address_short=_short_addr(str(w.get("address") or "")),
        status=STATUS_RUNNING if w.get("enabled") else STATUS_NOT_SET,
        allocation=float(w.get("allocation") or 0),
        pnl_today=0.0,
        trades_copied=0,
    )
    await send_or_edit(
        update, text,
        kb.wallet_card_kb(
            str(w.get("id") or "0"),
            running=bool(w.get("enabled")),
            page=page,
            total_pages=total_pages,
        ),
    )


async def _pause_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE, wallet_id: str) -> None:
    user = update.effective_user
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE copy_trade_tasks SET status='paused', updated_at=NOW()"
                        " WHERE id=$1::uuid AND user_id=$2::uuid",
                        wallet_id, u["id"],
                    )
            except Exception as exc:  # noqa: BLE001
                log.debug("wallet pause failed: %s", exc)
    await show_wallets(update, ctx)


async def _resume_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE, wallet_id: str) -> None:
    user = update.effective_user
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE copy_trade_tasks SET status='active', updated_at=NOW()"
                        " WHERE id=$1::uuid AND user_id=$2::uuid",
                        wallet_id, u["id"],
                    )
            except Exception as exc:  # noqa: BLE001
                log.debug("wallet resume failed: %s", exc)
    await show_wallets(update, ctx)


async def do_start_copying(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist new copy-wallet target to copy_trade_tasks (canonical execution
    table read by services/copy_trade/monitor.py)."""
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
    # MVP exposes $25/$50/$100/$250/Custom allocation buckets. Map to
    # copy_mode='fixed' with copy_amount = allocation_usdc. The production
    # scanner uses copy_amount directly when copy_mode='fixed'
    # (services/copy_trade/scaler.py:mirror_size_direct).
    addr = str(f["address"]).lower()
    allocation_usdc = float(f.get("allocation", 100.0))
    task_label = f"MVP {addr[:6]}...{addr[-4:]}"
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            # Manual upsert: copy_trade_tasks has no UNIQUE (user_id, wallet_address)
            # constraint, so re-add of the same wallet updates the most recent row
            # instead of inserting a duplicate.
            existing = await conn.fetchrow(
                """
                SELECT id FROM copy_trade_tasks
                WHERE user_id=$1 AND wallet_address=$2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                u["id"], addr,
            )
            if existing is not None:
                await conn.execute(
                    """
                    UPDATE copy_trade_tasks
                    SET status='active',
                        copy_mode='fixed',
                        copy_amount=$1,
                        copy_pct=NULL,
                        task_name=$2,
                        nickname=$2,
                        updated_at=NOW()
                    WHERE id=$3
                    """,
                    allocation_usdc, task_label, existing["id"],
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO copy_trade_tasks
                        (user_id, wallet_address, task_name, status,
                         copy_mode, copy_amount, nickname,
                         copy_direction, execution_mode, allow_topups)
                    VALUES ($1, $2, $3, 'active',
                            'fixed', $4, $3,
                            'buys_only', 'auto', true)
                    """,
                    u["id"], addr, task_label, allocation_usdc,
                )
            inserted = True
    except Exception as exc:  # noqa: BLE001
        log.debug("copy_trade_tasks insert unavailable: %s", exc)
    f["step"] = None
    if not inserted:
        log.warning("copy wallet add: persist failed; user %s", u["id"])
        await send_or_edit(
            update,
            "❌ <b>Failed to save wallet</b>\n\nDatabase error. Please try again.",
            kb.home_kb(),
        )
        return
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
                        """
                        UPDATE copy_trade_tasks
                           SET status='paused', updated_at=NOW()
                         WHERE user_id=$1 AND status='active'
                        """,
                        u["id"],
                    )
            except Exception as exc:  # noqa: BLE001
                log.debug("copy_trade_tasks pause update unavailable: %s", exc)
    await show_home(update, ctx)


async def show_resume_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_copy_resume_confirm(), kb.resume_confirm_kb())


async def do_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-activate all paused copy_trade_tasks for this user."""
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
                        UPDATE copy_trade_tasks
                           SET status='active', updated_at=NOW()
                         WHERE user_id=$1 AND status='paused'
                        """,
                        u["id"],
                    )
            except Exception as exc:  # noqa: BLE001
                log.debug("copy_trade_tasks resume update unavailable: %s", exc)
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
    activity_data = await _fetch_wallet_activity(addr)
    await update.message.reply_text(
        mvp.render_copy_wallet_review(
            address_short=_short_addr(addr),
            activity=activity_data["activity"],
            recent_trades=activity_data["recent_trades"],
            risk="🟡 Moderate",
        ),
        parse_mode="HTML",
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
        try:
            page = int(parts[2]) if len(parts) > 2 else 1
        except ValueError:
            page = 1
        await show_wallets(update, ctx, page=page); return
    if screen == "wallet":
        sub = parts[2] if len(parts) > 2 else ""
        wallet_id = parts[3] if len(parts) > 3 else ""
        if sub == "configure":
            await show_wallet_configure(update, ctx); return
        if sub == "start":
            await do_start_copying(update, ctx); return
        if sub == "edit":
            await show_wallet_configure(update, ctx); return
        if sub == "pause" and wallet_id:
            await _pause_wallet(update, ctx, wallet_id); return
        if sub == "resume" and wallet_id:
            await _resume_wallet(update, ctx, wallet_id); return
        if sub == "stats":
            # Stats view — show wallet card (full stats deferred)
            await show_wallets(update, ctx); return
        await show_wallets(update, ctx); return
    if screen == "pause":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "confirm":
            await do_pause(update, ctx); return
        await show_pause_confirm(update, ctx); return
    if screen == "resume":
        sub = parts[2] if len(parts) > 2 else None
        if sub == "confirm":
            await do_resume(update, ctx); return
        await show_resume_confirm(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_copy_cb, pattern=r"^copy:"))
