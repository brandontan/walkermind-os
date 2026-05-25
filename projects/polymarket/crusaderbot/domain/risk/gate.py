"""13-step risk gate. Every decision logged to risk_log."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import asyncpg

from ...database import get_pool
from ...wallet.ledger import daily_pnl, get_balance
from ..execution import fallback as live_fallback
from ..execution.slippage import check_market_impact
from ..ops.kill_switch import is_active as kill_switch_is_active
from . import constants as K

logger = logging.getLogger(__name__)


@dataclass
class GateContext:
    user_id: UUID
    telegram_user_id: int
    role: str
    auto_trade_on: bool
    paused: bool
    market_id: str
    side: str                 # "yes" | "no"
    proposed_size_usdc: Decimal
    proposed_price: float
    market_liquidity: float
    market_status: str
    edge_bps: float | None
    signal_ts: datetime | None
    idempotency_key: str
    strategy_type: str
    risk_profile: str
    daily_loss_override: float | None
    trading_mode: str         # 'paper' | 'live'
    # User-configured liquidity floor from user_settings.min_liquidity.
    # When > 0, overrides the profile default in gate step 11.
    # Allows users to lower the floor for thin markets (e.g. candle markets).
    user_min_liquidity: float = 0.0


@dataclass
class GateResult:
    approved: bool
    reason: str
    failed_step: int | None = None
    final_size_usdc: Decimal | None = None
    chosen_mode: str = "paper"


async def _log(user_id: UUID, market_id: str, step: int,
               approved: bool, reason: str) -> None:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO risk_log (user_id, market_id, gate_step, approved, reason)"
                " VALUES ($1, $2, $3, $4, $5)",
                user_id, market_id, step, approved, reason[:200],
            )
    except asyncpg.exceptions.ForeignKeyViolationError:
        # risk_log.user_id has FK on users.id. Operator /admin/dry-run uses
        # a synthetic user_id that doesn't exist — there's nothing to audit
        # and the FK is expected. Drop to debug so Sentry isn't paged on
        # every dry-run tick.
        logger.debug("risk_log skipped: synthetic user_id %s (dry-run)", user_id)
    except Exception as exc:
        logger.error("risk_log insert failed: %s", exc)


async def _open_position_count(user_id: UUID) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE user_id=$1 "
            "AND status IN ('open','pending_settlement')",
            user_id,
        ))


async def _open_exposure(user_id: UUID) -> Decimal:
    pool = get_pool()
    async with pool.acquire() as conn:
        return Decimal(await conn.fetchval(
            "SELECT COALESCE(SUM(size_usdc),0) FROM positions "
            "WHERE user_id=$1 AND status IN ('open','pending_settlement')",
            user_id,
        ))


async def _max_drawdown_breached(user_id: UUID) -> bool:
    """Drawdown vs initial deposits — halts user when MAX_DRAWDOWN_HALT crossed."""
    pool = get_pool()
    async with pool.acquire() as conn:
        deposits = Decimal(await conn.fetchval(
            "SELECT COALESCE(SUM(amount_usdc),0) FROM ledger "
            "WHERE user_id=$1 AND type='deposit'",
            user_id,
        ))
        balance = Decimal(await conn.fetchval(
            "SELECT COALESCE(balance_usdc,0) FROM wallets WHERE user_id=$1",
            user_id,
        ) or 0)
    if deposits <= 0:
        return False
    drawdown = (deposits - balance) / deposits
    return drawdown >= Decimal(str(K.MAX_DRAWDOWN_HALT))


async def _idempotent_already_seen(idem_key: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM idempotency_keys WHERE key=$1 AND expires_at>NOW()",
            idem_key,
        )
        return row is not None


async def _record_idempotency(user_id: UUID, idem_key: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO idempotency_keys (key, user_id, expires_at) "
            "VALUES ($1, $2, NOW() + INTERVAL '30 minutes') "
            "ON CONFLICT (key) DO NOTHING",
            idem_key, user_id,
        )


async def _recent_dup_market_trade(user_id: UUID, market_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM orders WHERE user_id=$1 AND market_id=$2 "
            "AND created_at > NOW() - ($3 * INTERVAL '1 second')",
            user_id, market_id, int(K.DEDUP_WINDOW_SECONDS),
        )
        return row is not None


def _passes_live_guards(ctx: GateContext, settings) -> bool:
    return (
        settings.ENABLE_LIVE_TRADING
        and settings.EXECUTION_PATH_VALIDATED
        and settings.CAPITAL_MODE_CONFIRMED
        and ctx.role == "admin"
        and ctx.trading_mode == "live"
    )


async def validate_risk_caps(user_id: UUID, proposed_size: Decimal) -> GateResult:
    """Hard caps applied before any order — Track D additions.

    These are absolute per-user ceilings independent of risk profile.
    Returns GateResult(approved=False, ...) on the first cap violation,
    GateResult(approved=True, "caps_ok") when all four pass.
    """
    from ...config import get_settings
    settings = get_settings()

    balance = await get_balance(user_id)

    # Cap 0: Available balance must be positive — no zero-balance trading
    if balance <= 0:
        return GateResult(
            False,
            "balance_zero_or_negative",
            0,
        )

    # Cap 1: Single position size (10% of balance)
    max_single = balance * Decimal(str(settings.MAX_SINGLE_POSITION_PCT))
    if proposed_size > max_single:
        return GateResult(
            False,
            f"position_size ${float(proposed_size):.2f} exceeds "
            f"{settings.MAX_SINGLE_POSITION_PCT*100:.0f}% cap "
            f"(${float(max_single):.2f})",
            0,
        )

    # Cap 2: Total exposure (80% of balance)
    open_exp = await _open_exposure(user_id)
    max_exp = balance * Decimal(str(settings.MAX_TOTAL_EXPOSURE_PCT))
    if open_exp + proposed_size > max_exp:
        return GateResult(False, "total_exposure_cap_80pct", 0)

    # Cap 3: Daily loss floor (default -$50, env-configurable)
    today_pnl = await daily_pnl(user_id)
    if today_pnl <= Decimal(str(settings.MAX_DAILY_LOSS_USD)):
        return GateResult(
            False,
            f"daily_loss_cap_usd ${float(today_pnl):.2f} <= "
            f"${settings.MAX_DAILY_LOSS_USD:.2f}",
            0,
        )

    # Cap 4: Open positions count (hard cap 20)
    open_count = await _open_position_count(user_id)
    if open_count >= settings.MAX_OPEN_POSITIONS:
        return GateResult(
            False,
            f"max_open_positions_{settings.MAX_OPEN_POSITIONS}_reached",
            0,
        )

    return GateResult(True, "caps_ok")


async def evaluate(ctx: GateContext) -> GateResult:
    """Run the 13 gates. Default chosen_mode is paper unless live guards pass."""
    from ...config import get_settings
    settings = get_settings()
    profile = K.profile_or_default(ctx.risk_profile)

    # 0. Hard risk caps (Track D) — fail fast before any gate logging
    caps_result = await validate_risk_caps(ctx.user_id, ctx.proposed_size_usdc)
    if not caps_result.approved:
        await _log(ctx.user_id, ctx.market_id, 0, False, caps_result.reason)
        return caps_result
    await _log(ctx.user_id, ctx.market_id, 0, True, "ok")

    # 1. Kill switch — read goes through the domain module so we hit the
    # 30s in-process cache instead of the DB on every signal evaluation.
    if await kill_switch_is_active():
        await _log(ctx.user_id, ctx.market_id, 1, False, "kill_switch_active")
        # If the user was in live mode when the kill switch tripped, drop
        # them to paper so the next signal does not retry live the moment
        # the operator releases the switch. R12 live-to-paper fallback.
        if ctx.trading_mode == "live":
            try:
                await live_fallback.trigger_for_kill_switch_halt(ctx.user_id)
            except Exception as fb_exc:  # noqa: BLE001
                logger.error("kill_switch fallback trigger failed: %s", fb_exc)
        return GateResult(False, "kill_switch_active", 1)
    await _log(ctx.user_id, ctx.market_id, 1, True, "ok")

    # 2. User pause / auto-trade off
    if ctx.paused or not ctx.auto_trade_on:
        await _log(ctx.user_id, ctx.market_id, 2, False, "auto_trade_off_or_paused")
        return GateResult(False, "auto_trade_off_or_paused", 2)
    await _log(ctx.user_id, ctx.market_id, 2, True, "ok")

    # 3. Paper trading is open to every user (no gate). Live retains an
    #    admin-role check as defence-in-depth; the authoritative live
    #    safety boundary is assert_live_guards (role=='admin' + activation
    #    guards) at order submission, which is intentionally left intact.
    if ctx.trading_mode == "live" and ctx.role != "admin":
        await _log(ctx.user_id, ctx.market_id, 3, False, f"role_{ctx.role}")
        return GateResult(False, "insufficient_role", 3)
    await _log(ctx.user_id, ctx.market_id, 3, True, "ok")

    # 4. Strategy availability
    if ctx.strategy_type not in K.STRATEGY_AVAILABILITY:
        await _log(ctx.user_id, ctx.market_id, 4, False, "unknown_strategy")
        return GateResult(False, "unknown_strategy", 4)
    if ctx.risk_profile not in K.STRATEGY_AVAILABILITY[ctx.strategy_type]:
        await _log(ctx.user_id, ctx.market_id, 4, False,
                   f"strategy_{ctx.strategy_type}_not_for_{ctx.risk_profile}")
        return GateResult(False, "strategy_unavailable_for_profile", 4)
    # Custom profile requires capital_alloc_pct to be configured in user_settings.
    if ctx.risk_profile == "custom":
        pool = get_pool()
        async with pool.acquire() as conn:
            cap_alloc = await conn.fetchval(
                "SELECT capital_alloc_pct FROM user_settings WHERE user_id = $1",
                ctx.user_id,
            )
        if cap_alloc is None:
            await _log(ctx.user_id, ctx.market_id, 4, False, "custom_risk_not_configured")
            return GateResult(False, "custom_risk_not_configured", 4)
    await _log(ctx.user_id, ctx.market_id, 4, True, "ok")

    # 5. Daily loss limit
    pnl = await daily_pnl(ctx.user_id)
    cap = K.effective_daily_loss(ctx.risk_profile, ctx.daily_loss_override)
    if float(pnl) <= cap:
        await _log(ctx.user_id, ctx.market_id, 5, False,
                   f"daily_loss {pnl} <= {cap}")
        return GateResult(False, "daily_loss_cap_hit", 5)
    await _log(ctx.user_id, ctx.market_id, 5, True, "ok")

    # 6. Max drawdown
    if await _max_drawdown_breached(ctx.user_id):
        await _log(ctx.user_id, ctx.market_id, 6, False, "max_drawdown_halt")
        if ctx.trading_mode == "live":
            try:
                await live_fallback.trigger_for_drawdown_halt(ctx.user_id)
            except Exception as fb_exc:  # noqa: BLE001
                logger.error("drawdown fallback trigger failed: %s", fb_exc)
        return GateResult(False, "max_drawdown_halt", 6)
    await _log(ctx.user_id, ctx.market_id, 6, True, "ok")

    # 7. Concurrent trades
    cur = await _open_position_count(ctx.user_id)
    if cur >= profile["max_concurrent"]:
        await _log(ctx.user_id, ctx.market_id, 7, False,
                   f"max_concurrent {cur}/{profile['max_concurrent']}")
        return GateResult(False, "max_concurrent_trades", 7)
    await _log(ctx.user_id, ctx.market_id, 7, True, "ok")

    # 8. Correlated exposure
    balance = await get_balance(ctx.user_id)
    open_exp = await _open_exposure(ctx.user_id)
    if balance > 0 and (open_exp + ctx.proposed_size_usdc) / balance > Decimal(
        str(K.MAX_CORRELATED_EXPOSURE)
    ):
        await _log(ctx.user_id, ctx.market_id, 8, False, "correlated_exposure")
        return GateResult(False, "correlated_exposure_cap", 8)
    await _log(ctx.user_id, ctx.market_id, 8, True, "ok")

    # 9. Signal staleness
    if ctx.signal_ts is not None:
        now = datetime.now(timezone.utc)
        age = (now - ctx.signal_ts).total_seconds()
        if age > K.SIGNAL_STALE_SECONDS:
            await _log(ctx.user_id, ctx.market_id, 9, False, f"stale_{int(age)}s")
            return GateResult(False, "signal_stale", 9)
    await _log(ctx.user_id, ctx.market_id, 9, True, "ok")

    # 10. Idempotency / dedup
    if await _idempotent_already_seen(ctx.idempotency_key):
        await _log(ctx.user_id, ctx.market_id, 10, False, "idempotent_dup")
        return GateResult(False, "idempotent_duplicate", 10)
    if await _recent_dup_market_trade(ctx.user_id, ctx.market_id):
        await _log(ctx.user_id, ctx.market_id, 10, False, "dedup_window")
        return GateResult(False, "dedup_window_active", 10)
    await _log(ctx.user_id, ctx.market_id, 10, True, "ok")

    # 11. Liquidity floor — user override takes precedence when set.
    # User sets min_liquidity in WebTrader Market Filter (user_settings.min_liquidity).
    # For candle markets the profile floor (10k-20k) is too high; user can lower it.
    _profile_floor = float(profile["min_liquidity"])
    _user_floor = float(ctx.user_min_liquidity) if ctx.user_min_liquidity > 0 else _profile_floor
    min_liq = max(_user_floor, K.MIN_LIQUIDITY * 0.1)  # hard floor: 10% of system MIN (1k USDC)
    if ctx.market_liquidity < min_liq:
        await _log(ctx.user_id, ctx.market_id, 11, False,
                   f"liquidity {ctx.market_liquidity}<{min_liq}")
        return GateResult(False, "insufficient_liquidity", 11)
    await _log(ctx.user_id, ctx.market_id, 11, True, "ok")

    # 12. Edge floor
    if ctx.edge_bps is not None:
        min_edge = max(profile["min_edge_bps"], K.MIN_EDGE_BPS)
        if ctx.edge_bps < min_edge:
            await _log(ctx.user_id, ctx.market_id, 12, False,
                       f"edge {ctx.edge_bps}bps<{min_edge}")
            return GateResult(False, "insufficient_edge", 12)
    await _log(ctx.user_id, ctx.market_id, 12, True, "ok")

    # 13. Market status + size cap + final mode selection
    if ctx.market_status != "active":
        await _log(ctx.user_id, ctx.market_id, 13, False,
                   f"market_status_{ctx.market_status}")
        return GateResult(False, "market_inactive", 13)
    # Fractional Kelly enforcement (CLAUDE.md hard rule: a=0.25, full Kelly forbidden).
    # Global K.KELLY_FRACTION acts as the hard cap; per-profile kelly is clamped to it.
    assert 0 < K.KELLY_FRACTION <= 0.5, \
        f"KELLY_FRACTION {K.KELLY_FRACTION} out of safe range"
    kelly = min(float(profile.get("kelly", K.KELLY_FRACTION)), K.KELLY_FRACTION)
    max_pos_pct = float(profile["max_pos_pct"])
    assert 0 < max_pos_pct < 1.0, \
        f"max_pos_pct {max_pos_pct} must be < 1.0"
    max_pos_size = balance * Decimal(str(max_pos_pct)) * Decimal(str(kelly))
    final_size = min(ctx.proposed_size_usdc, max_pos_size)
    if final_size <= 0:
        await _log(ctx.user_id, ctx.market_id, 13, False, "size_zero_after_cap")
        return GateResult(False, "size_zero_after_cap", 13)

    chosen_mode = "live" if _passes_live_guards(ctx, settings) else "paper"
    if ctx.trading_mode == "live" and chosen_mode == "paper":
        await _log(ctx.user_id, ctx.market_id, 13, True,
                   "live_requested_but_guards_failed_falling_back_to_paper")
        try:
            await live_fallback.trigger_for_live_guard_unset(ctx.user_id)
        except Exception as fb_exc:  # noqa: BLE001
            logger.error(
                "live_guard_unset gate fallback trigger failed: %s", fb_exc,
            )
    await _log(ctx.user_id, ctx.market_id, 13, True, f"approved_{chosen_mode}")

    # 14. Slippage / market-impact guard
    impact_result = check_market_impact(final_size, ctx.market_liquidity)
    if not impact_result.accepted:
        await _log(ctx.user_id, ctx.market_id, 14, False, impact_result.reason)
        return GateResult(False, "market_impact_cap", 14)
    await _log(ctx.user_id, ctx.market_id, 14, True,
               f"impact_ok_{impact_result.impact_pct:.4f}")

    await _record_idempotency(ctx.user_id, ctx.idempotency_key)
    return GateResult(True, "approved", None, final_size, chosen_mode)





