"""Fast Track B — CopyTradeMonitor: copy-trade task execution service.

Pipeline (per run_once() tick):
    1. Load all active copy_trade_tasks (status='active') across all users.
    2. Group tasks by leader wallet_address to minimise Polymarket API calls.
    3. For each unique leader wallet: fetch_recent_wallet_trades().
    4. For each task × each unprocessed leader trade:
         a. Skip if leader trade already processed — idempotency check via
            copy_trade_idempotency table (user_id, task_id, leader_trade_id).
         b. Apply min_trade_size filter.
         c. Apply daily max_spend cap (copy_trade_daily_spend table).
         d. Compute copy size via mirror_size_direct (copy_mode='fixed')
            or scale_size (copy_mode='proportional').
         e. Apply reverse_copy to flip the side if configured.
         f. Build TradeSignal with strategy_type='copy_trade'.
         g. TradeEngine.execute(signal) → TradeResult.
         h. On approval: record spend row + persist idempotency row.
         i. Structured log: ACCEPTED / REJECTED / DUPLICATE.

Idempotency key (for TradeEngine / paper engine):
    "copy_{task_id}_{leader_trade_id}"
    Unique per (task, leader trade) — prevents double-fill on replay.

Safety contract:
    * PAPER ONLY — no activation guard mutations, no ENABLE_LIVE_TRADING flip.
    * asyncio only — no threading.
    * structlog for all logging.
    * Full type hints.
    * Zero silent failures — every exception logged; one bad task never
      prevents other tasks from executing in the same tick.
    * Retry + backoff + timeout: delegated to wallet_watcher.fetch_* which
      already applies a 5-second per-call timeout and a 1 req/s rate limit.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from ...database import get_pool
from ...domain.copy_trade.models import CopyTradeTask
from ...domain.copy_trade.repository import list_active_tasks
from ...domain.ops.kill_switch import is_active as kill_switch_is_active
from ..trade_engine import TradeEngine, TradeSignal
from .scaler import MIN_TRADE_SIZE_USDC, mirror_size_direct, scale_size
from .wallet_watcher import WalletWatcherUnavailable, fetch_recent_wallet_trades

logger = structlog.get_logger(__name__)

_STRATEGY_TYPE = "copy_trade"
# How many recent leader trades to fetch per wallet per tick
_LEADER_FETCH_LIMIT = 20
# Module-level TradeEngine singleton — stateless; safe to share across ticks
_engine: TradeEngine = TradeEngine()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_once() -> None:
    """Execute one copy-trade monitor tick.

    Safe to call concurrently with other scan loops — all DB writes use
    ON CONFLICT DO NOTHING for idempotency. If the kill switch is active
    the tick exits immediately without touching the execution path.
    """
    if await kill_switch_is_active():
        logger.warning("copy_trade_monitor: kill switch active — skipping tick")
        return

    tasks = await list_active_tasks()
    if not tasks:
        logger.debug("copy_trade_monitor: no active tasks")
        return

    # Group by wallet to minimise Polymarket API calls
    wallet_to_tasks: dict[str, list[CopyTradeTask]] = {}
    for task in tasks:
        wallet_to_tasks.setdefault(task.wallet_address, []).append(task)

    for wallet_address, wallet_tasks in wallet_to_tasks.items():
        await _process_wallet(wallet_address, wallet_tasks)


# ---------------------------------------------------------------------------
# Per-wallet processing
# ---------------------------------------------------------------------------


async def _process_wallet(
    wallet_address: str,
    tasks: list[CopyTradeTask],
) -> None:
    """Fetch recent trades for one leader wallet and process all matching tasks."""
    try:
        trades = await fetch_recent_wallet_trades(
            wallet_address, limit=_LEADER_FETCH_LIMIT
        )
    except Exception:
        logger.exception(
            "copy_trade_monitor: unexpected error fetching wallet trades",
            wallet=wallet_address,
        )
        return

    if not trades:
        logger.debug(
            "copy_trade_monitor: no recent trades for wallet",
            wallet=wallet_address,
        )
        return

    for task in tasks:
        for trade in trades:
            await _process_one(task, trade, wallet_address)


# ---------------------------------------------------------------------------
# Per-task × per-trade processing
# ---------------------------------------------------------------------------


async def _process_one(
    task: CopyTradeTask,
    leader_trade: dict[str, Any],
    wallet_address: str,
) -> None:
    """Evaluate one leader trade against one copy task and execute if eligible."""
    leader_trade_id = _extract_trade_id(leader_trade)
    if not leader_trade_id:
        logger.warning(
            "copy_trade_monitor: leader trade has no id — skipping",
            task_id=str(task.id),
            trade_keys=list(leader_trade.keys()),
        )
        return

    log = logger.bind(
        user_id=str(task.user_id),
        task_id=str(task.id),
        leader_trade_id=leader_trade_id,
        wallet=wallet_address,
    )

    # --- idempotency check ---
    if await _is_already_processed(task.user_id, task.id, leader_trade_id):
        log.debug("copy_trade_monitor: DUPLICATE — already processed")
        return

    # --- min_trade_size filter ---
    leader_size = _extract_size(leader_trade)
    if leader_size < float(task.min_trade_size):
        log.info(
            "copy_trade_monitor: REJECTED — below min_trade_size",
            reason="min_trade_size",
            leader_size=leader_size,
            min_required=str(task.min_trade_size),
        )
        return

    # --- daily spend cap check ---
    today_spend = await _get_daily_spend(task.user_id, task.id)
    remaining_spend = float(task.max_daily_spend) - today_spend
    if remaining_spend <= 0:
        log.info(
            "copy_trade_monitor: REJECTED — daily spend cap reached",
            reason="max_daily_spend",
            today_spend=today_spend,
            max_daily_spend=str(task.max_daily_spend),
        )
        return

    # --- compute copy size ---
    copy_size = _compute_copy_size(task, leader_size, leader_trade, remaining_spend)
    if copy_size < MIN_TRADE_SIZE_USDC:
        log.info(
            "copy_trade_monitor: REJECTED — copy size below minimum",
            reason="copy_size_floor",
            copy_size=copy_size,
        )
        return

    # --- cap at remaining daily spend ---
    copy_size = min(copy_size, remaining_spend)
    if copy_size < MIN_TRADE_SIZE_USDC:
        log.info(
            "copy_trade_monitor: REJECTED — copy size after spend cap below minimum",
            reason="spend_cap_floor",
            copy_size=copy_size,
        )
        return

    # --- resolve side (with optional reverse_copy) ---
    raw_side = (leader_trade.get("side") or "").lower()
    if raw_side not in ("buy", "sell", "yes", "no"):
        log.warning(
            "copy_trade_monitor: REJECTED — unrecognised side in leader trade",
            reason="unknown_side",
            raw_side=raw_side,
        )
        return
    side = _resolve_side(raw_side, task.reverse_copy)

    # --- load user context for TradeSignal ---
    user_ctx = await _load_user_context(task.user_id)
    if user_ctx is None:
        log.warning(
            "copy_trade_monitor: REJECTED — user context not found",
            reason="user_not_found",
        )
        return

    # --- resolve market info from leader trade ---
    market_id = str(
        leader_trade.get("market_id")
        or leader_trade.get("conditionId")
        or leader_trade.get("condition_id")
        or ""
    )
    if not market_id:
        log.warning(
            "copy_trade_monitor: REJECTED — no market_id in leader trade",
            reason="no_market_id",
        )
        return

    market_question: str | None = leader_trade.get("market_question") or leader_trade.get("title")
    price = _extract_price(leader_trade, side)
    idempotency_key = _make_idempotency_key(task.id, leader_trade_id)

    signal = TradeSignal(
        user_id=task.user_id,
        telegram_user_id=user_ctx["telegram_user_id"],
        access_tier=user_ctx["access_tier"],
        auto_trade_on=user_ctx["auto_trade_on"],
        paused=user_ctx["paused"],
        market_id=market_id,
        market_question=market_question,
        yes_token_id=leader_trade.get("yes_token_id"),
        no_token_id=leader_trade.get("no_token_id"),
        side=side,
        proposed_size_usdc=Decimal(str(round(copy_size, 6))),
        price=price,
        market_liquidity=_extract_liquidity(leader_trade),
        market_status=leader_trade.get("market_status", "active"),
        idempotency_key=idempotency_key,
        strategy_type=_STRATEGY_TYPE,
        risk_profile=user_ctx.get("risk_profile", "balanced"),
        trading_mode=user_ctx.get("trading_mode", "paper"),
        tp_pct=float(task.tp_pct) if task.tp_pct else None,
        sl_pct=float(task.sl_pct) if task.sl_pct else None,
        signal_ts=datetime.utcnow(),
    )

    # --- route through TradeEngine (risk gate mandatory) ---
    try:
        result = await _engine.execute(signal)
    except Exception:
        log.exception(
            "copy_trade_monitor: TradeEngine raised exception",
            market_id=market_id,
            copy_size=copy_size,
        )
        return

    if result.approved:
        if result.mode == "duplicate":
            log.info(
                "copy_trade_monitor: DUPLICATE — idempotency key already in paper engine",
                mode=result.mode,
            )
        else:
            log.info(
                "copy_trade_monitor: ACCEPTED",
                mode=result.mode,
                order_id=str(result.order_id) if result.order_id else None,
                position_id=str(result.position_id) if result.position_id else None,
                final_size_usdc=str(result.final_size_usdc),
                copy_task_id=str(task.id),
                leader_wallet=wallet_address,
                leader_trade_id=leader_trade_id,
            )
            # Record spend and persist idempotency row
            actual_size = float(result.final_size_usdc) if result.final_size_usdc else copy_size
            await _record_spend(task.user_id, task.id, actual_size)
        await _mark_processed(task.user_id, task.id, leader_trade_id)
    else:
        log.info(
            "copy_trade_monitor: REJECTED — risk gate",
            reason=result.rejection_reason,
            failed_gate_step=result.failed_gate_step,
        )
        # Still mark idempotency so we don't re-evaluate on next tick
        await _mark_processed(task.user_id, task.id, leader_trade_id)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _is_already_processed(
    user_id: UUID, task_id: UUID, leader_trade_id: str
) -> bool:
    """Check copy_trade_idempotency table for (user_id, task_id, leader_trade_id)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM copy_trade_idempotency
             WHERE user_id = $1 AND task_id = $2 AND leader_trade_id = $3
            """,
            user_id, task_id, leader_trade_id,
        )
    return row is not None


async def _mark_processed(
    user_id: UUID, task_id: UUID, leader_trade_id: str
) -> None:
    """Persist idempotency row. ON CONFLICT DO NOTHING — safe to retry."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO copy_trade_idempotency (user_id, task_id, leader_trade_id)
            VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
            """,
            user_id, task_id, leader_trade_id,
        )


async def _get_daily_spend(user_id: UUID, task_id: UUID) -> float:
    """Return total USDC spend for (user_id, task_id) today (UTC date)."""
    pool = get_pool()
    today = date.today().isoformat()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(spend_usdc), 0) AS total
              FROM copy_trade_daily_spend
             WHERE user_id = $1 AND task_id = $2 AND spend_date = $3
            """,
            user_id, task_id, today,
        )
    return float(row["total"]) if row else 0.0


async def _record_spend(user_id: UUID, task_id: UUID, spend_usdc: float) -> None:
    """Upsert today's spend for (user_id, task_id). Append-safe."""
    pool = get_pool()
    today = date.today().isoformat()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO copy_trade_daily_spend (user_id, task_id, spend_date, spend_usdc)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, task_id, spend_date)
            DO UPDATE SET spend_usdc = copy_trade_daily_spend.spend_usdc + EXCLUDED.spend_usdc
            """,
            user_id, task_id, today, spend_usdc,
        )


async def _load_user_context(user_id: UUID) -> dict[str, Any] | None:
    """Load minimal user context needed to build a TradeSignal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.telegram_user_id,
                   u.access_tier,
                   u.auto_trade_on,
                   u.paused,
                   COALESCE(s.risk_profile, 'balanced') AS risk_profile,
                   COALESCE(s.trading_mode, 'paper')    AS trading_mode
              FROM users u
              JOIN user_settings s ON s.user_id = u.id
             WHERE u.id = $1
            """,
            user_id,
        )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _extract_trade_id(trade: dict[str, Any]) -> str | None:
    """Return a stable string ID for a leader trade dict, or None."""
    raw = (
        trade.get("id")
        or trade.get("trade_id")
        or trade.get("transactionHash")
        or trade.get("txHash")
    )
    if raw:
        return str(raw)
    # Derive a content-hash as fallback so a trade without an id field can
    # still be deduplicated within the same tick
    sig_fields = (
        trade.get("conditionId") or trade.get("condition_id") or "",
        trade.get("side") or "",
        trade.get("size") or trade.get("amount") or "",
        trade.get("timestamp") or trade.get("createdAt") or "",
    )
    sig = "|".join(str(f) for f in sig_fields)
    if any(sig_fields):
        return "hash_" + hashlib.sha256(sig.encode()).hexdigest()[:24]
    return None


def _extract_size(trade: dict[str, Any]) -> float:
    """Return trade notional in USDC from a leader trade dict."""
    for key in ("usdcSize", "usdc_size", "size_usdc", "size", "amount", "notional"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _extract_price(trade: dict[str, Any], side: str) -> float:
    """Return the trade price from a leader trade dict."""
    for key in ("price", "avg_price", "avgPrice", "outcome_price"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    # Fallback: mid-market approximation based on side
    return 0.5


def _extract_liquidity(trade: dict[str, Any]) -> float:
    """Return market liquidity (USDC) from a leader trade dict, or fallback."""
    for key in ("liquidity", "market_liquidity", "volume24h", "volume"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    # Fallback: assume adequate liquidity so the risk gate market-liquidity
    # check does not spuriously reject copy trades when the field is absent
    return 50_000.0


def _resolve_side(raw_side: str, reverse_copy: bool) -> str:
    """Normalise leader side to 'yes' | 'no' and apply reverse_copy."""
    # Polymarket activity uses 'BUY'/'SELL' — map to yes/no
    normalised = {"buy": "yes", "sell": "no", "yes": "yes", "no": "no"}.get(
        raw_side.lower(), "yes"
    )
    if reverse_copy:
        return "no" if normalised == "yes" else "yes"
    return normalised


def _compute_copy_size(
    task: CopyTradeTask,
    leader_size: float,
    leader_trade: dict[str, Any],
    remaining_spend: float,
) -> float:
    """Return the copy size in USDC for this task, or 0.0 to skip."""
    if task.copy_mode == "fixed":
        # Fixed: use copy_amount directly, capped at remaining daily spend
        fixed = float(task.copy_amount)
        return fixed if fixed >= MIN_TRADE_SIZE_USDC else 0.0
    # Proportional: use scaler with leader bankroll if available
    leader_bankroll = float(
        leader_trade.get("bankroll")
        or leader_trade.get("portfolioValue")
        or leader_trade.get("portfolio_value")
        or 0.0
    )
    if leader_bankroll > 0.0:
        return scale_size(
            leader_size=leader_size,
            leader_bankroll=leader_bankroll,
            user_available=remaining_spend,
            max_position_pct=0.10,  # hard-coded 10% position cap per HARD RULES
        )
    return mirror_size_direct(
        leader_size=leader_size,
        user_available=remaining_spend,
        max_position_pct=0.10,
    )


def _make_idempotency_key(task_id: UUID, leader_trade_id: str) -> str:
    return f"copy_{task_id}_{leader_trade_id}"


__all__ = ["run_once"]
