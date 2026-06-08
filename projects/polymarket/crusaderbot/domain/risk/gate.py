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
from . import slippage_gate as SG

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
    # User-configured drawdown halt threshold (0, 0.08]. System 8% floor applies
    # regardless — this only lets users halt earlier (e.g. set 5% to stop at 5%).
    max_drawdown_pct: float | None = None
    # Per-user live-trading capital cap (USDC). Aggregate live exposure +
    # this proposed size must stay below this cap. 0 = live trading
    # disabled for this user (any live trade rejected at step 15). Set
    # via /api/web/live/enable (typed confirm) or Telegram /enable_live.
    # Paper trades are unaffected — the cap only fires when the gate is
    # about to approve a chosen_mode='live' trade.
    live_capital_cap_usdc: float = 0.0
    # Per-user concurrent-trades override (1..20). None = use profile default.
    # Gate step 7 picks min(profile_default, this) — user can only tighten.
    max_concurrent_override: int | None = None
    # Copy-trade and similar per-task opt-in flows have their own explicit
    # "start" gate (e.g. copy_trade_tasks.status='active'). When True, step 2
    # skips the global auto_trade_on requirement but STILL honours ctx.paused
    # so /pause halts everything. All other risk caps (size, daily loss,
    # drawdown, concurrency, liquidity, kill switch, live guards) still apply.
    bypass_auto_trade_check: bool = False
    # Complete-set arbitrage (Lane 2C). When True the gate is being run ONCE for a
    # hedged YES+NO pair, with proposed_size_usdc = the COMBINED fillable cost of
    # the set (not a single leg). The booking primitive (book_complete_set_paper)
    # consumes a fixed-share quote, so step 13 must NOT silently Kelly-shrink the
    # size (that would desync the approved size from the booked legs): instead it
    # hard-rejects when the combined cost exceeds the per-position cap and passes
    # the size through unchanged otherwise. The scan sizes the quote within the
    # cap up front (max_shares), so a reject here means a real misconfiguration.
    complete_set: bool = False
    # Robustness gate (Phase-2c-1b). False only when the module that produced this
    # candidate is classified UNTRADEABLE (Monte Carlo OOS) and ROBUSTNESS_GATE_ENABLED
    # is on. Default True → no effect. AND-ed into the live guards, so it can only
    # DOWNGRADE a would-be live trade to paper — never enable live. Paper is unaffected.
    module_live_eligible: bool = True
    # WARP-87 (Sub-Lane C slippage gate): the trading cell ("{asset}/{timeframe}",
    # e.g. "btc/5m") plus the live order-book inputs the LIVE-only tiered slippage
    # gate (domain/risk/slippage_gate.py) consumes. All optional/defaulted so the
    # existing GateContext construction sites are unchanged — populating them at the
    # candidate sources is the proposal's documented follow-up lane. When ``cell``
    # is None no per-cell LIVE size cap applies; ``orderbook_depth_usdc`` falls back
    # to ``market_liquidity`` and ``spread`` to the 1.0 fair complete-set value
    # (zero spread cost) for the deterministic slippage estimate.
    cell: str | None = None
    orderbook_depth_usdc: float | None = None
    spread: float | None = None
    # WARP-89 (gate-hotpath-db-fix): the user's authoritative risk-profile CAP%
    # (capital_alloc_pct), PRELOADED once per user per tick by the orchestrator and
    # passed in so the per-candidate ``evaluate`` hot path performs ZERO asyncpg
    # calls for it. This replaced the per-candidate ``SELECT capital_alloc_pct FROM
    # user_settings`` that caused the Jun-7 prod wedge (one pool acquire per
    # candidate under a saturated pool). Optional/defaulted so every existing
    # GateContext construction site stays byte-compatible: when None, ``evaluate``
    # falls back to the one-shot DB loader ``load_user_capital_alloc`` (correct, but
    # does a DB read — only construction sites OUTSIDE the per-candidate scan loop
    # hit that path). Populate it with ``resolve_capital_alloc_pct`` so the value
    # carries the exact profile-default fallback + 80% clamp semantics.
    capital_alloc_pct: float | None = None


@dataclass
class GateResult:
    approved: bool
    reason: str
    failed_step: int | None = None
    final_size_usdc: Decimal | None = None
    chosen_mode: str = "paper"


async def _log(user_id: UUID, market_id: str, step: int,
               approved: bool, reason: str) -> None:
    """Emit a risk-gate decision to stdout (+ Sentry on rejection). No DB write.

    WARP-82 (kill-realtime-persistence): the former risk_log write is
    replaced by a severity-gated dual sink — a rejection (``approved=False``) is
    a WARNING-level Sentry capture (with structured extra) so operators still see
    it; an approval is an info stdout line. Never raises into the gate loop.
    """
    reason = (reason or "")[:200]
    try:
        if not approved:
            try:
                import sentry_sdk
                sentry_sdk.capture_message(
                    f"risk_gate reject step={step} user={user_id} "
                    f"market={market_id} reason={reason}",
                    level="warning",
                )
            except Exception:  # noqa: BLE001 — sentry optional, never break the gate
                pass
            logger.warning(
                "risk_event approved=False step=%s market_id=%s reason=%s",
                step, market_id, reason,
            )
        else:
            logger.info(
                "risk_event approved=True step=%s market_id=%s", step, market_id,
            )
    except Exception as exc:  # noqa: BLE001 — observability must not break the gate
        logger.error("risk_event log failed: %s", exc)


async def _open_position_count(user_id: UUID) -> int:
    """Open-position count for the step-7 concurrency cap, counting a complete-set
    arb (two `paired_position_id`-linked legs) as ONE unit, not two.

    A complete set is one economic decision booked as two rows; without this it
    would burn the concurrency budget at 2x. `LEAST(id, COALESCE(paired, id))`
    collapses both legs of a set to a single group key (they share the same
    minimum), counts a directional row as itself, and is robust to the transient
    state where one leg has closed (the lone open leg still counts as 1). With no
    paired rows present the expression reduces to `COUNT(DISTINCT id)` =
    `COUNT(*)`, so the count is unchanged until complete sets exist.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            "SELECT COUNT(DISTINCT LEAST(id, COALESCE(paired_position_id, id))) "
            "FROM positions WHERE user_id=$1 "
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


# Absolute hard ceiling on total capital deployment — mirrors the custom-profile
# capital_alloc_pct bound in the WebTrader (set_risk_profile). No profile or
# custom value may deploy more than this fraction of equity.
_MAX_DEPLOYMENT_PCT: float = 0.80


def resolve_capital_alloc_pct(raw: object, profile: str) -> float:
    """Pure resolver: raw ``user_settings.capital_alloc_pct`` value + profile -> CAP%.

    The authoritative total capital-deployment cap. Owner directive (2026-06-08):
    the risk-profile capital_alloc_pct (conservative 0.20 / balanced 0.40 /
    aggressive 0.60 / custom ≤0.80) governs how much of the user's equity may sit in
    open positions, and SUPERSEDES the legacy system-wide correlated-exposure
    ceiling (``MAX_CORRELATED_EXPOSURE`` = 0.40) so Aggressive can deploy beyond 40%.
    ``raw`` is the stored ``user_settings.capital_alloc_pct`` (or ``None`` for a
    legacy/NULL row); falls back to the profile default, then balanced 0.40. Clamped
    to ``_MAX_DEPLOYMENT_PCT`` so no misconfiguration can push deployment past the
    absolute 80% ceiling.

    WARP-89: extracted from the former ``_capital_alloc_pct`` so the per-tick
    orchestrator can resolve the value from a row it already fetched (preloaded into
    ``GateContext.capital_alloc_pct``) WITHOUT a per-candidate DB read, while the
    one-shot DB loader (``load_user_capital_alloc``) and the resolver share one set
    of fallback + clamp semantics.
    """
    if raw is not None:
        try:
            val = float(raw)
            if val > 0:
                return min(val, _MAX_DEPLOYMENT_PCT)
        except (TypeError, ValueError):
            pass
    prof = K.PROFILE_TP_SL.get((profile or "balanced").lower())
    return float(prof["capital_alloc_pct"]) if prof else 0.40


async def load_user_capital_alloc(user_id: UUID, profile: str) -> float:
    """One-shot DB loader for the user's authoritative risk-profile CAP%.

    Reads ``user_settings.capital_alloc_pct`` ONCE and resolves it through
    ``resolve_capital_alloc_pct``. WARP-89: this is the SINGLE source for the
    preload — the orchestrator calls it (or resolves an already-fetched row) once
    per user per tick BEFORE the candidate loop and passes the result into every
    GateContext via ``capital_alloc_pct``. It must NOT be invoked inside the
    per-candidate ``evaluate`` path (that was the Jun-7 prod-wedge DB hit). It
    remains the fallback for legacy GateContext construction sites that do not yet
    preload the value (those are outside the hot scan loop).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT capital_alloc_pct FROM user_settings WHERE user_id = $1",
            user_id,
        )
    return resolve_capital_alloc_pct(raw, profile)


# Backward-compatible alias for the crash-recovery resume path and any caller that
# still wants the one-shot DB loader by the old name. WARP-89 renamed the public
# helper to ``load_user_capital_alloc``; the per-candidate hot path no longer calls
# either (it reads the preloaded ``GateContext.capital_alloc_pct``).
_capital_alloc_pct = load_user_capital_alloc


async def _max_drawdown_breached(user_id: UUID,
                                  user_drawdown_pct: float | None = None) -> bool:
    """Drawdown vs initial deposits — halts when threshold crossed.

    threshold = min(MAX_DRAWDOWN_HALT=8%, user_drawdown_pct) so users can only
    make the halt *stricter* (earlier), never weaker than the system floor.
    """
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
    threshold = K.MAX_DRAWDOWN_HALT
    if user_drawdown_pct is not None and 0 < user_drawdown_pct < threshold:
        threshold = user_drawdown_pct
    drawdown = (deposits - balance) / deposits
    return drawdown >= Decimal(str(threshold))


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
        and settings.RISK_CONTROLS_VALIDATED
        and settings.SECURITY_HARDENING_VALIDATED
        # Mirror assert_live_guards: USE_REAL_CLOB must be on too, otherwise this
        # would label a trade chosen_mode='live' that the router bounces to paper.
        and settings.USE_REAL_CLOB
        and ctx.role == "admin"
        and ctx.trading_mode == "live"
    )


async def _robustness_downgrade(chosen_mode: str, ctx: GateContext) -> str:
    """Phase-2c-1b: force an UNTRADEABLE module to paper — WITHOUT tripping the
    user-level live fallback.

    Applied AFTER the live-guard fallback block in ``evaluate`` so it is a pure,
    per-candidate ``live → paper`` downgrade: it does NOT call
    ``live_fallback.trigger_for_live_guard_unset`` (which would persistently flip
    the user's ``trading_mode`` and disable live for their *other* eligible modules
    too — Codex P1, PR #1581).

    Two ways a module is held to paper, so EVERY live-routing caller is covered
    (Codex P2 — there are several direct TradeSignal/GateContext constructors:
    _process_candidate, fast_topup, copy_trade, complete_set):
      1. Explicit ``ctx.module_live_eligible=False`` — the precise per-module value
         the scan loop threads (it knows the playbook sub-module via selected_module,
         which is finer-grained than ctx.strategy_type). Short-circuits, no DB read.
      2. Gate-side lookup by ``(strategy_type, risk_profile)`` against the cached
         UNTRADEABLE set — covers callers that don't thread the flag.
    Gated by ``ROBUSTNESS_GATE_ENABLED`` + fail-soft (any error / flag off → no
    downgrade). Never upgrades paper → live.
    """
    if chosen_mode != "live":
        return chosen_mode
    if not ctx.module_live_eligible:
        return "paper"
    try:
        from ...config import get_settings
        if not bool(getattr(get_settings(), "ROBUSTNESS_GATE_ENABLED", False)):
            return "live"
        from ..research.robustness import untradeable_set
        if (ctx.strategy_type, ctx.risk_profile) in await untradeable_set(mode="paper"):
            return "paper"
    except Exception as exc:  # noqa: BLE001 — a gate-lookup fault must never block trading
        logger.error("robustness_gate_lookup_failed: %s", exc)
    return "live"


async def validate_risk_caps(
    user_id: UUID,
    proposed_size: Decimal,
    max_open_cap: int | None = None,
) -> GateResult:
    """Hard per-user ceilings independent of risk profile.

    Three checks remain after the C-5/C-6 reconciliation:
      Cap 0 — balance must be positive (no zero-balance trading).
      Cap 1 — single position size (``MAX_SINGLE_POSITION_PCT`` of balance).
      Cap 4 — total open position count (``MAX_OPEN_POSITIONS``).

    The historical Cap 2 (total exposure %) and Cap 3 (per-user daily-loss USD
    floor) were profile-shadowing duplicates of gate steps 8 and 5 respectively
    — step 8 was always tighter (0.40 < 0.60) and step 5's profile cap was
    always shadowed by the −$50 settings floor. Both ``MAX_TOTAL_EXPOSURE_PCT``
    and ``MAX_DAILY_LOSS_USD`` now participate in the most-restrictive
    selection inside ``effective_exposure_cap`` / ``effective_daily_loss``
    (evaluated at gate steps 8 / 5), so the operator can still tighten via
    env without two gates fighting and the UI's profile limit becomes the
    true enforced limit when the operator does not.
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

    # Cap 1: Single position size (MAX_SINGLE_POSITION_PCT of balance)
    max_single = balance * Decimal(str(settings.MAX_SINGLE_POSITION_PCT))
    if proposed_size > max_single:
        return GateResult(
            False,
            f"position_size ${float(proposed_size):.2f} exceeds "
            f"{settings.MAX_SINGLE_POSITION_PCT*100:.0f}% cap "
            f"(${float(max_single):.2f})",
            0,
        )

    # Cap 4: Open positions count — PER USER (owner directive 2026-06-03).
    # ``max_open_cap`` is the caller's per-user effective limit (profile default
    # or the user's own override, via K.effective_max_concurrent). When absent
    # (direct callers / tests) it falls back to the operator backstop
    # settings.MAX_OPEN_POSITIONS. There is no global ceiling clamping it down —
    # the user's own setting governs; step 7 enforces the same value.
    open_count = await _open_position_count(user_id)
    open_cap = (
        int(max_open_cap)
        if max_open_cap is not None
        else int(settings.MAX_OPEN_POSITIONS)
    )
    if open_count >= open_cap:
        return GateResult(
            False,
            f"max_open_positions_{open_cap}_reached",
            0,
        )

    return GateResult(True, "caps_ok")


async def evaluate(ctx: GateContext) -> GateResult:
    """Run the 13 gates. Default chosen_mode is paper unless live guards pass."""
    from ...config import get_settings
    settings = get_settings()
    profile = K.profile_or_default(ctx.risk_profile)

    # 0. Hard risk caps (Track D) — fail fast before any gate logging
    caps_result = await validate_risk_caps(
        ctx.user_id,
        ctx.proposed_size_usdc,
        max_open_cap=K.effective_max_concurrent(
            ctx.risk_profile, ctx.max_concurrent_override,
        ),
    )
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
    #    Paused is always honoured. auto_trade_on can be bypassed by per-task
    #    opt-in flows (copy-trade tasks with status='active') — see
    #    GateContext.bypass_auto_trade_check.
    if ctx.paused:
        await _log(ctx.user_id, ctx.market_id, 2, False, "paused")
        return GateResult(False, "auto_trade_off_or_paused", 2)
    if not ctx.auto_trade_on and not ctx.bypass_auto_trade_check:
        await _log(ctx.user_id, ctx.market_id, 2, False, "auto_trade_off")
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

    # 5. Daily loss limit — most restrictive of system hard stop, profile cap,
    #    user override, and operator env floor (MAX_DAILY_LOSS_USD). Step 0 cap 3
    #    used to enforce MAX_DAILY_LOSS_USD separately and always shadowed the
    #    profile cap; routing it through effective_daily_loss removes the
    #    duplicate evaluation while preserving the most-restrictive semantics.
    pnl = await daily_pnl(ctx.user_id)
    cap = K.effective_daily_loss(
        ctx.risk_profile,
        ctx.daily_loss_override,
        system_floor=float(settings.MAX_DAILY_LOSS_USD),
    )
    if float(pnl) <= cap:
        await _log(ctx.user_id, ctx.market_id, 5, False,
                   f"daily_loss {pnl} <= {cap}")
        return GateResult(False, "daily_loss_cap_hit", 5)
    await _log(ctx.user_id, ctx.market_id, 5, True, "ok")

    # 6. Max drawdown
    if await _max_drawdown_breached(ctx.user_id, ctx.max_drawdown_pct):
        await _log(ctx.user_id, ctx.market_id, 6, False, "max_drawdown_halt")
        if ctx.trading_mode == "live":
            try:
                await live_fallback.trigger_for_drawdown_halt(ctx.user_id)
            except Exception as fb_exc:  # noqa: BLE001
                logger.error("drawdown fallback trigger failed: %s", fb_exc)
        return GateResult(False, "max_drawdown_halt", 6)
    await _log(ctx.user_id, ctx.market_id, 6, True, "ok")

    # 7. Concurrent trades — most-restrictive of profile cap and user override.
    cur = await _open_position_count(ctx.user_id)
    max_concurrent = K.effective_max_concurrent(
        ctx.risk_profile, ctx.max_concurrent_override,
    )
    if cur >= max_concurrent:
        await _log(ctx.user_id, ctx.market_id, 7, False,
                   f"max_concurrent {cur}/{max_concurrent}")
        return GateResult(False, "max_concurrent_trades", 7)
    await _log(ctx.user_id, ctx.market_id, 7, True, "ok")

    # 8. Total capital-deployment cap — the user's risk-profile CAP%
    #    (capital_alloc_pct) is authoritative: total open cost + this proposed
    #    trade must stay within equity × cap% (conservative 20% / balanced 40% /
    #    aggressive 60% / custom ≤80%). Owner directive (2026-06-08): cap% governs
    #    deployment per profile and OVERRIDES the legacy system-wide
    #    correlated-exposure ceiling (0.40) so Aggressive can deploy beyond 40%.
    #    Denominator is equity (free balance + open cost) — the same pool the
    #    sizing engine allocates against — so the cap reads as a true % of equity.
    balance = await get_balance(ctx.user_id)
    open_exp = await _open_exposure(ctx.user_id)
    equity = balance + open_exp
    # WARP-89: read the PRELOADED CAP% from the context — NO per-candidate DB read.
    # The orchestrator resolves capital_alloc_pct once per user per tick (before the
    # candidate loop) via ``load_user_capital_alloc`` / ``resolve_capital_alloc_pct``
    # and threads it in. ``None`` only for legacy construction sites outside the hot
    # scan loop, which fall back to the one-shot DB loader (correct, but a DB read).
    if ctx.capital_alloc_pct is not None:
        deploy_cap = ctx.capital_alloc_pct
    else:
        # Module-level name (alias of load_user_capital_alloc) so the fallback is
        # monkeypatchable by name in tests of legacy non-preloaded construction
        # sites; the per-candidate hot path never reaches this branch.
        deploy_cap = await _capital_alloc_pct(ctx.user_id, ctx.risk_profile)
    if equity > 0 and (open_exp + ctx.proposed_size_usdc) / equity > Decimal(
        str(deploy_cap)
    ):
        await _log(ctx.user_id, ctx.market_id, 8, False,
                   f"capital_deployment cap={deploy_cap:.4f}")
        return GateResult(False, "capital_deployment_cap", 8)
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
    if not (0 < K.KELLY_FRACTION <= 0.25):
        raise ValueError(
            f"KELLY_FRACTION {K.KELLY_FRACTION} out of safe range (0, 0.25] "
            "(CLAUDE.md hard rule — full Kelly forbidden)"
        )
    kelly = min(float(profile.get("kelly", K.KELLY_FRACTION)), K.KELLY_FRACTION)
    max_pos_pct = float(profile["max_pos_pct"])
    assert 0 < max_pos_pct < 1.0, \
        f"max_pos_pct {max_pos_pct} must be < 1.0"
    max_pos_size = balance * Decimal(str(max_pos_pct)) * Decimal(str(kelly))
    if ctx.complete_set:
        # A complete-set quote is a fixed YES+NO share count; Kelly-shrinking the
        # combined cost would desync the approved size from the legs the booker
        # will buy. Enforce the cap as a hard reject (the scan already sized the
        # quote within it) and pass the combined cost through unchanged.
        final_size = ctx.proposed_size_usdc
        if final_size <= 0:
            await _log(ctx.user_id, ctx.market_id, 13, False, "size_zero_after_cap")
            return GateResult(False, "size_zero_after_cap", 13)
        if final_size > max_pos_size:
            await _log(ctx.user_id, ctx.market_id, 13, False,
                       f"complete_set_size_over_cap {final_size}>{max_pos_size}")
            return GateResult(False, "complete_set_size_over_cap", 13)
    else:
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

    # Robustness downgrade — applied AFTER the live-guard fallback above so an
    # UNTRADEABLE module is forced to paper per-candidate WITHOUT tripping the
    # user-level fallback (which would persistently disable the user's live mode
    # for their other eligible modules too — Codex P1, PR #1581).
    _pre_robust_mode = chosen_mode
    chosen_mode = await _robustness_downgrade(chosen_mode, ctx)
    if chosen_mode != _pre_robust_mode:
        await _log(ctx.user_id, ctx.market_id, 13, True,
                   "robustness_downgrade_untradeable_to_paper")

    await _log(ctx.user_id, ctx.market_id, 13, True, f"approved_{chosen_mode}")

    # 14. Slippage / market-impact guard
    impact_result = check_market_impact(final_size, ctx.market_liquidity)
    if not impact_result.accepted:
        await _log(ctx.user_id, ctx.market_id, 14, False, impact_result.reason)
        return GateResult(False, "market_impact_cap", 14)
    await _log(ctx.user_id, ctx.market_id, 14, True,
               f"impact_ok_{impact_result.impact_pct:.4f}")

    # 14b. Tiered LIVE-cutover slippage gate (WARP-83 Sub-Lane C -> WARP-87).
    #      RISK-stage only; runs ONLY for a trade about to route LIVE — paper
    #      (~$7) leaves the size-dependent impact term dormant and paper accrual
    #      still feeds the EV cutover analysis, so paper is intentionally
    #      untouched. PURE hot path: the slippage magnitude comes from the
    #      deterministic estimator and the tier / size-cap verdict is a pure
    #      function — NO DB read here (the #1694 pool-wedge lesson; see
    #      docs/rca/2026-06-07-gate-hotpath-incident.md). GREEN passes; WATCH
    #      passes with a structured log + Sentry breadcrumb; HALT and a per-cell
    #      LIVE size-cap breach reject cleanly (no exception).
    if chosen_mode == "live":
        # Lazy import: the estimator lives under domain/research, whose package
        # __init__ pulls DB-backed modules. Deferring it to the live path keeps the
        # risk-gate module-import light and DB-free (paper/CI never load research).
        from ..research.slippage_estimator import estimate_slippage_bps
        _depth = (
            float(ctx.orderbook_depth_usdc)
            if ctx.orderbook_depth_usdc is not None
            else float(ctx.market_liquidity)
        )
        _spread = float(ctx.spread) if ctx.spread is not None else 1.0
        _est = estimate_slippage_bps(
            stake_usdc=float(final_size),
            orderbook_depth_usdc=_depth,
            spread=_spread,
            entry_price=float(ctx.proposed_price),
        )
        _slip = SG.evaluate_slippage_gate(
            cell=ctx.cell,
            proposed_size_usdc=float(final_size),
            slippage_bps=_est.total_bps,
            gross_edge_bps=ctx.edge_bps,
        )
        if _slip.rejected:
            await _log(
                ctx.user_id, ctx.market_id, 14, False,
                f"{_slip.reason} tier={_slip.tier.value} "
                f"slip_bps={_est.total_bps:.1f} cell={ctx.cell}",
            )
            return GateResult(False, _slip.reason, 14)
        if _slip.tier is SG.SlippageTier.WATCH:
            _frac = _slip.slippage_frac_of_edge or 0.0
            logger.warning(
                "slippage_watch market_id=%s cell=%s slip_bps=%.1f "
                "frac_of_edge=%.4f size=%.2f",
                ctx.market_id, ctx.cell, _est.total_bps, _frac, float(final_size),
            )
            try:
                import sentry_sdk
                sentry_sdk.add_breadcrumb(
                    category="risk.slippage",
                    level="warning",
                    message="slippage_watch",
                    data={
                        "market_id": ctx.market_id,
                        "cell": ctx.cell,
                        "slippage_bps": round(_est.total_bps, 1),
                        "frac_of_edge": _slip.slippage_frac_of_edge,
                        "size_usdc": float(final_size),
                    },
                )
            except Exception:  # noqa: BLE001 — sentry optional, never break the gate
                pass
            await _log(ctx.user_id, ctx.market_id, 14, True,
                       f"slippage_watch frac={_frac:.4f}")
        else:
            await _log(ctx.user_id, ctx.market_id, 14, True, "slippage_green")

    # 15. Per-user LIVE capital cap (Axis #3, WARP/ROOT-live-activation-flow).
    #     Fires only when the gate is about to approve a chosen_mode='live'
    #     trade. The user MUST have opted into live mode via
    #     /api/web/live/enable (typed-confirm flow) or Telegram /enable_live
    #     — both writers set users_settings.live_capital_cap_usdc > 0.
    #     A cap of zero means the user has NOT opted in; any live trade
    #     for them is rejected.
    #     Aggregate exposure check: open-live size + this proposed size
    #     must stay below the cap, so a user with cap=$50 cannot have one
    #     $30 position plus a new $40 trade. Paper trades skip this gate.
    if chosen_mode == "live":
        cap = max(0.0, float(ctx.live_capital_cap_usdc or 0.0))
        if cap <= 0.0:
            await _log(ctx.user_id, ctx.market_id, 15, False, "live_not_opted_in")
            return GateResult(False, "live_not_opted_in", 15)
        open_live = await _open_live_exposure(ctx.user_id)
        if (float(open_live) + float(final_size)) > cap:
            await _log(
                ctx.user_id, ctx.market_id, 15, False,
                f"live_capital_cap_exceeded open={open_live:.2f} "
                f"proposed={float(final_size):.2f} cap={cap:.2f}",
            )
            return GateResult(False, "live_capital_cap_exceeded", 15)
        await _log(
            ctx.user_id, ctx.market_id, 15, True,
            f"live_cap_ok open={open_live:.2f} cap={cap:.2f}",
        )

    await _record_idempotency(ctx.user_id, ctx.idempotency_key)
    return GateResult(True, "approved", None, final_size, chosen_mode)


async def _open_live_exposure(user_id: UUID) -> Decimal:
    """Aggregate USDC currently deployed across the user's open LIVE
    positions. Used by gate step 15 to enforce ``live_capital_cap_usdc``.

    Returns ``Decimal("0")`` on any DB error so a transient outage does
    NOT silently approve a live trade past the cap — the caller still
    needs the cap > proposed size, so an open exposure read of zero
    cannot grant approval that wouldn't have already been granted.
    """
    try:
        from ...database import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT COALESCE(SUM(size_usdc), 0) "
                "FROM positions "
                "WHERE user_id = $1::uuid "
                "  AND mode = 'live' "
                "  AND status IN ('open', 'pending_settlement')",
                user_id,
            )
        return Decimal(str(val or 0))
    except Exception as exc:  # noqa: BLE001 — fail-closed: zero exposure read
        logger.warning("live_capital_cap exposure read failed: %s", exc)
        return Decimal("0")


async def resume_safety_check(
    *,
    user_id: UUID,
    market_id: str,
    risk_profile: str,
    proposed_size_usdc: Decimal,
    trading_mode: str,
    chosen_mode: str,
    daily_loss_override: float | None = None,
    max_drawdown_pct: float | None = None,
    live_capital_cap_usdc: float = 0.0,
    max_concurrent_override: int | None = None,
) -> GateResult:
    """Capital-circuit-breaker re-check for crash-recovery resume.

    A 'queued' execution_queue row is resumed by routing it straight to the
    execution router WITHOUT re-running the full 15-step gate, because gate
    step 9 (staleness) and step 10 (idempotency/dedup) would self-reject a
    legitimately-recovered trade (the idempotency key is already recorded and
    the original signal is >4h old by the time a crash is recovered). That
    bypass must NOT extend to the account circuit breakers: a user who has
    since breached their daily-loss cap, drawdown halt, concurrent limit,
    exposure cap, or live capital cap must NOT have a pending entry resumed.
    This helper re-evaluates exactly that subset (gate steps 5, 6, 7, 8, 15)
    and nothing else.

    Intentionally skipped (documented): staleness (9), dedup/idempotency (10),
    liquidity (11), edge (12), market status (13), market impact (14). These
    are entry-quality gates, not capital circuit breakers, and several require
    live market data not persisted on the queue row. Kill-switch is handled by
    the caller so a halted-then-released switch leaves the row queued for retry
    rather than abandoning it.

    Returns GateResult(approved=True, "resume_safety_ok") when the account is
    clear, or GateResult(approved=False, reason, failed_step) on the first
    breached circuit breaker. Never records idempotency.
    """
    profile = K.profile_or_default(risk_profile)

    # 0. Available balance must be positive — mirrors gate step 0 cap 0. A resume
    #    must never open a new position on a zero/negative-balance account. The
    #    balance is fetched once here and reused by the exposure check (step 8)
    #    so the resume path issues a single get_balance query.
    balance = await get_balance(user_id)
    if balance <= 0:
        await _log(user_id, market_id, 0, False, "resume_balance_zero_or_negative")
        return GateResult(False, "balance_zero_or_negative", 0)

    # 5. Daily loss limit
    pnl = await daily_pnl(user_id)
    cap = K.effective_daily_loss(risk_profile, daily_loss_override)
    if float(pnl) <= cap:
        await _log(user_id, market_id, 5, False, f"resume_daily_loss {pnl} <= {cap}")
        return GateResult(False, "daily_loss_cap_hit", 5)

    # 6. Max drawdown halt
    if await _max_drawdown_breached(user_id, max_drawdown_pct):
        await _log(user_id, market_id, 6, False, "resume_max_drawdown_halt")
        return GateResult(False, "max_drawdown_halt", 6)

    # 7. Concurrent trades — most-restrictive of profile cap and user override.
    cur = await _open_position_count(user_id)
    max_concurrent = K.effective_max_concurrent(risk_profile, max_concurrent_override)
    if cur >= max_concurrent:
        await _log(user_id, market_id, 7, False,
                   f"resume_max_concurrent {cur}/{max_concurrent}")
        return GateResult(False, "max_concurrent_trades", 7)

    # 8. Total capital-deployment cap — same per-user CAP% authority as the main
    #    gate path (capital_alloc_pct supersedes the legacy 0.40 ceiling; owner
    #    directive 2026-06-08). Denominator is equity (balance + open cost).
    open_exp = await _open_exposure(user_id)
    equity = balance + open_exp
    deploy_cap = await _capital_alloc_pct(user_id, risk_profile)
    if equity > 0 and (open_exp + proposed_size_usdc) / equity > Decimal(
        str(deploy_cap)
    ):
        await _log(user_id, market_id, 8, False, "resume_capital_deployment")
        return GateResult(False, "capital_deployment_cap", 8)

    # 15. Per-user LIVE capital cap — only when resuming a live-mode trade.
    if chosen_mode == "live":
        cap_live = max(0.0, float(live_capital_cap_usdc or 0.0))
        if cap_live <= 0.0:
            await _log(user_id, market_id, 15, False, "resume_live_not_opted_in")
            return GateResult(False, "live_not_opted_in", 15)
        open_live = await _open_live_exposure(user_id)
        if (float(open_live) + float(proposed_size_usdc)) > cap_live:
            await _log(
                user_id, market_id, 15, False,
                f"resume_live_capital_cap_exceeded open={open_live:.2f} "
                f"proposed={float(proposed_size_usdc):.2f} cap={cap_live:.2f}",
            )
            return GateResult(False, "live_capital_cap_exceeded", 15)

    await _log(user_id, market_id, 0, True, "resume_safety_ok")
    return GateResult(True, "resume_safety_ok")





