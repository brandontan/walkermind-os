"""P3d signal scan job — per-user signal_following scan loop + execution queue.

Pipeline (per user, per scan tick):
    1. Load users enrolled in signal_following + auto_trade_on + Tier 3+
    2. Build UserContext + MarketFilters from DB row
    3. SignalFollowingStrategy.scan() -> list[SignalCandidate]  (pure DB reads)
    4. Per candidate:
       a. execution_queue pre-check: skip if publication_id already present
       b. Build TradeSignal; run TradeEngine.execute() (gate + paper fill)
       c. On approval: INSERT into execution_queue + mark executed
       d. Log outcome: accepted | duplicate | skipped_dedup | rejected | failed

Deduplication (dual-layer):
    Outer — execution_queue UNIQUE (user_id, publication_id) — permanent;
            prevents re-execution after a prior tick already submitted.
    Inner — idempotency_keys 30-min window (risk gate step 10) — short-circuit
            for recent risk rejections so the gate is not re-evaluated every
            30 s during a transient block (e.g. max_concurrent_trades).

Crash recovery:
    A prior tick may have inserted a 'queued' row and crashed before the
    paper engine completed. This path resumes via router_execute directly
    (bypassing TradeEngine / re-running the risk gate) because:
      * Gate step 10 rejects the same idempotency_key for 30 min.
      * Gate step 9 rejects stale signals after the 4h staleness window
        (SIGNAL_STALE_SECONDS=14400). Step 1c in _process_candidate enforces
        a tighter 30-min window for feed publications before gate execution.
      * Crash-recovery re-fetches current market prices at resume time, so
        stale entry prices are not a concern on this path.
    The crash-recovery router call is the ONLY place router_execute is used
    directly in this module. All normal execution paths go through TradeEngine.

Safety:
    * No activation guard mutations.
    * Risk gate is mandatory inside TradeEngine; router_execute is never
      called without approval on the normal path.
    * No HTTP fetches.  No threading — asyncio only.
    * Every exception is caught, logged, and does NOT propagate to the caller
      so one bad user/publication cannot crash the whole scan tick.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math as _math
import random
import time as _time
import uuid as _uuid_mod
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import UUID

import structlog

from ...core import event_bus as _event_bus
from ...database import get_pool
from ...domain.execution.router import execute as router_execute
from ...domain.ops.kill_switch import is_active as kill_switch_is_active
from ...domain.risk.constants import PROFILES
from ...domain.strategy.registry import StrategyRegistry
from ...domain.strategy.types import MarketFilters, SignalCandidate, UserContext
from ...integrations import polymarket as _polymarket
from ...integrations.polymarket import get_live_market_price
from ..trade_engine import TradeEngine, TradeResult, TradeSignal
from .lib_strategy_runner import DEFERRED_STRATEGIES, ENABLED_STRATEGIES
from ..signal_feed.signal_evaluator import evaluate_publications_for_user

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRATEGY_NAME = "signal_following"

# Maximum age of a signal_publication before it is rejected for execution.
# Signals older than this window have stale entry prices — the market has
# already moved, making fills unrealistic. 30 minutes is conservative;
# the signal_publications.expires_at window (4h) is intentionally longer
# to support feed UI history display, NOT to gate execution.
_MAX_SIGNAL_AGE_SECONDS: int = 1800  # 30 minutes

# Maximum allowed drift between a signal's target_price and the current
# cached market price before the candidate is rejected. 25% tolerates
# normal intra-day volatility while blocking 300–1000% stale fills.
# No API call required — uses market data already loaded in step 2.
_MAX_TARGET_DRIFT_PCT: float = 0.25  # 25%

# ---------------------------------------------------------------------------
# Preset → lib strategy name mapping
# ---------------------------------------------------------------------------

# lib/strategies/* were archived in WARP/R00T/strategy-system-cleanup — none
# had a reachable user-facing preset. ENABLED_STRATEGIES / DEFERRED_STRATEGIES
# are now empty tuples; this frozenset stays empty until a future strategy is
# wired with a real preset path.
_LIB_STRATEGY_NAMES: frozenset[str] = frozenset(ENABLED_STRATEGIES) | frozenset(DEFERRED_STRATEGIES)

_LATE_ENTRY_V3_NAME = "late_entry_v3"

# Domain strategies the scan loop invokes explicitly (registered via
# bootstrap_default_strategies()). Each runs its own crypto-only eligibility
# gate inside scan(), so emitted candidates already satisfy the asset whitelist.
_DOMAIN_STRATEGY_NAMES: frozenset[str] = frozenset({_LATE_ENTRY_V3_NAME})

# Preset → strategies it may fire. Narrowed to the 3 candle presets (all
# routing to late_entry_v3) after WARP/R00T/strategy-system-cleanup. A user
# with no active_preset is skipped at the top of run_once().
_PRESET_ALLOWED: dict[str | None, frozenset[str]] = {
    "close_sweep": frozenset({_LATE_ENTRY_V3_NAME}),
    "safe_close":  frozenset({_LATE_ENTRY_V3_NAME}),
    "flip_hunter": frozenset({_LATE_ENTRY_V3_NAME}),
}


# ---------------------------------------------------------------------------
# Scan run telemetry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Monitor-only asset hygiene (WARP/R00T/bnb-monitor-only, ref Polybot
# directive Part 4 Tier 3). Assets listed here are NOT tradable — the
# webtrader router validator rejects them at preset-activation time, but
# existing user rows persisted before this lane was shipped can still
# carry them in their `selected_assets` JSONB array. We strip those
# entries here so the scanner never includes monitor-only markets in
# any user's signal universe, even on legacy data. The user's next
# preset re-activation through the router normalises the DB column.
#
# Add to this set when an asset graduates to monitor-only; remove when
# 30-day edge stats validate re-enabling (directive Part 4 Phase 2).
# ---------------------------------------------------------------------------
_MONITOR_ONLY_ASSETS: frozenset[str] = frozenset({"BNB"})


def _filter_monitor_only_assets(assets: Any) -> list[str]:
    """Drop monitor-only assets from a persisted ``selected_assets`` row.

    Returns a list (not tuple) so call sites can keep the existing
    ``selected_assets: list[str]`` typing. Empty / None input yields
    an empty list. Comparison is case-insensitive — DB rows may have
    been written before the router normalised to uppercase.

    Defensive type handling: the ``selected_assets`` column is currently
    ``TEXT[]`` so asyncpg returns a Python list, but if it ever migrates
    to JSONB (or some upstream caller hands us a JSON-encoded string),
    iterating the raw string would walk characters one-by-one and
    produce nonsense. Parse stringified JSON first; reject any other
    non-sequence type rather than crashing.
    """
    if assets is None:
        return []
    if isinstance(assets, str):
        # Empty string short-circuits without touching json.loads.
        if not assets.strip():
            return []
        try:
            parsed = json.loads(assets)
        except Exception:
            return []
        # Only accept the parsed value if it's actually a list (a JSON
        # string like '"BTC"' decodes to a bare string — reject that).
        if not isinstance(parsed, list):
            return []
        assets = parsed
    if not isinstance(assets, (list, tuple, set, frozenset)):
        return []
    out: list[str] = []
    for a in assets:
        sym = str(a).strip().upper()
        if not sym:
            continue
        if sym in _MONITOR_ONLY_ASSETS:
            continue
        out.append(sym)
    return out


# =====================================================================
# Bankroll dynamic sizing multiplier
# (WARP/R00T/bankroll-dynamic-sizing, Lane 5/5 Polybot directive)
# =====================================================================
#
# Per-user EMA-smoothed bankroll baseline. The multiplier compares the
# user's current balance to its slow-moving baseline and scales the
# proposed trade size proportionally, bounded by [MIN, MAX]. Effect:
#   - Recent winners get slightly larger entries (up to MAX)
#   - Recent losers get slightly smaller entries (down to MIN)
#   - First observation seeds the baseline → multiplier = 1.0 (no change)
#
# In-process state (same lifecycle as Lane 4 direction window): a Fly
# restart re-seeds baselines on next scan, briefly returning all users
# to multiplier=1.0 — acceptable soft-reset, far cheaper than a DB
# write per scan tick. Disable entirely via
# BANKROLL_DYNAMIC_SIZING_ENABLED=false (escape hatch).
_bankroll_ema_baseline: dict[str, float] = {}
_bankroll_ema_baseline_active: dict[str, float] = {}  # frozen pre-update baseline for current tick
_bankroll_ema_last_update: dict[str, float] = {}  # monotonic timestamp


def _bankroll_multiplier(
    user_id: str,
    current_balance: float,
    *,
    multiplier_min: float,
    multiplier_max: float,
    ema_alpha: float,
    min_update_interval_sec: float = 0.0,
) -> float:
    """Return the sizing multiplier for (user, current_balance) and
    conditionally update the EMA-smoothed baseline as a side effect.

    ``min_update_interval_sec``: throttle the baseline update so that
    multiple candidates processed for the same user within a single
    scan tick (e.g. several markets for the same late_entry_v3 user)
    do NOT each drift the baseline toward `current_balance`. Without
    the throttle, N intra-tick candidates collapse the baseline to ~=
    current, defeating the multiplier. Set to 0 to update on every
    call (test convenience).

    Fail-safe: returns 1.0 (no scaling) when current_balance is not a
    positive finite number, when no prior baseline exists (first
    observation seeds it), or when the multiplier evaluates non-finite.
    """
    if not _math.isfinite(current_balance) or current_balance <= 0:
        return 1.0
    key = str(user_id)
    baseline = _bankroll_ema_baseline.get(key)
    now_mono = _time.monotonic()
    if baseline is None or baseline <= 0:
        # First observation: seed both dicts; multiplier neutral.
        _bankroll_ema_baseline[key] = current_balance
        _bankroll_ema_baseline_active[key] = current_balance
        _bankroll_ema_last_update[key] = now_mono
        return 1.0
    # Throttle the EMA update: only refresh baseline when sufficient
    # time has elapsed since the last update. Inside a single scan tick
    # all candidates for the same user share the prior (active) baseline,
    # so each candidate's multiplier reflects the true deviation, not the
    # already-dragged-toward-current intra-tick artifact.
    # _bankroll_ema_baseline_active freezes the pre-update baseline so
    # subsequent intra-tick calls use the same reference even after the
    # EMA dict has been advanced.
    last_update = _bankroll_ema_last_update.get(key, 0.0)
    if (now_mono - last_update) >= min_update_interval_sec:
        _bankroll_ema_baseline_active[key] = baseline  # freeze pre-update value
        _bankroll_ema_baseline[key] = (
            ema_alpha * current_balance + (1.0 - ema_alpha) * baseline
        )
        _bankroll_ema_last_update[key] = now_mono
    active_baseline = _bankroll_ema_baseline_active.get(key, baseline)
    raw_multiplier = current_balance / active_baseline
    if not _math.isfinite(raw_multiplier):
        return 1.0
    # Clamp to operator-configured bounds. Default [0.5, 1.5] caps both
    # the upside (don't blow up on a recent win streak) and the downside
    # (don't shrink positions so small they hit min-size gates).
    return max(multiplier_min, min(multiplier_max, raw_multiplier))


# --------------------------------------------------------------------
# Bankroll circuit breaker (WARP/R00T/bankroll-circuit-breaker, ref
# Polybot directive 1.4 + #6). Per-user latch: trips when current
# balance falls below `baseline * threshold`, resumes only after
# climbing back to `baseline * threshold * (1 + hysteresis)`. The
# baseline is the slow-moving _bankroll_ema_baseline maintained by
# Lane 5 — same source of truth, no duplicate state.
#
# Default OFF (config-gated dark launch). When the latch is True the
# gate in _process_candidate returns early with
# scan_outcome="skipped_circuit_breaker". Existing open positions and
# TP/SL exits are unaffected — the gate blocks NEW entries only.
# --------------------------------------------------------------------
_bankroll_circuit_tripped: dict[str, bool] = {}

# --------------------------------------------------------------------
# Fast top-up state (WARP/R00T/flip-hunter-fast-topup, Polybot directive
# 1.5 + 1.3.2). Per-(user, market) monotonic timestamp of the last
# top-up fired so we can enforce the FAST_TOPUP_COOLDOWN_SECONDS gate.
# In-process state; a Fly restart clears it (acceptable — the next
# eligible safe_close/flip_hunter entry simply re-arms the cooldown).
# --------------------------------------------------------------------
_fast_topup_last_at: dict[str, float] = {}


def _fast_topup_reset_for_tests() -> None:
    """Clear the per-(user, market) cooldown tracker. Tests use this
    to isolate runs."""
    _fast_topup_last_at.clear()


def _fast_topup_key(user_id: Any, market_id: str) -> str:
    return f"{str(user_id)}:{market_id}"


def _ensure_bankroll_baseline_seeded(user_id: str, current_balance: float) -> None:
    """Seed the per-user EMA baseline with ``current_balance`` if absent.

    Decouples the circuit breaker from Lane 5's dynamic-sizing knob:
    when ``BANKROLL_DYNAMIC_SIZING_ENABLED=false`` the multiplier path
    never seeds ``_bankroll_ema_baseline``, leaving the breaker without
    a reference to measure deviation against. This helper seeds on
    first observation (multiplier-neutral; current_balance becomes the
    reference) so the breaker has something to compare against even
    when sizing is off.

    Does NOT advance the EMA — only seeds. Advancement remains the
    multiplier's job so Lane 5's throttle semantics are preserved.
    No-op when a baseline already exists.
    """
    if not _math.isfinite(current_balance) or current_balance <= 0:
        return
    key = str(user_id)
    if key in _bankroll_ema_baseline:
        return
    _bankroll_ema_baseline[key] = current_balance
    _bankroll_ema_baseline_active[key] = current_balance
    _bankroll_ema_last_update[key] = _time.monotonic()


def _evaluate_bankroll_circuit_breaker(
    user_id: str,
    current_balance: float,
    *,
    threshold: float,
    hysteresis: float,
) -> bool:
    """Update the per-user circuit-breaker latch and return its new state.

    State transitions (per directive 1.4 + #6):
      - Tripped when ``current_balance < baseline * threshold``
      - Resumes when ``current_balance > baseline * threshold * (1 + hysteresis)``
      - Below the resume bound but above the trip bound: latch holds
        whatever state it had — that's the hysteresis cushion that
        prevents the "circuit breaker loop" failure mode (Appendix C).

    Fail-safe: returns False (NOT tripped) when no baseline exists yet
    (first observation — can't measure deviation against an unknown
    reference), when current balance is non-positive / non-finite, or
    when threshold computation evaluates non-finite.
    """
    if not _math.isfinite(current_balance) or current_balance <= 0:
        return False
    key = str(user_id)
    # Use the latest computed baseline (not the per-tick frozen
    # `_bankroll_ema_baseline_active`): the breaker compares against
    # the user's current EMA reference, and the log payload should
    # reflect the same value so an operator debugging a trip sees the
    # exact denominator the gate used.
    baseline = _bankroll_ema_baseline.get(key)
    if baseline is None or baseline <= 0:
        return False
    trip_bound = baseline * threshold
    resume_bound = trip_bound * (1.0 + hysteresis)
    if not (_math.isfinite(trip_bound) and _math.isfinite(resume_bound)):
        return False
    was_tripped = _bankroll_circuit_tripped.get(key, False)
    if was_tripped:
        # Latched: only release if balance has climbed past the resume bound.
        if current_balance > resume_bound:
            _bankroll_circuit_tripped[key] = False
            return False
        return True
    # Not yet tripped: trip if balance has fallen below the trip bound.
    if current_balance < trip_bound:
        _bankroll_circuit_tripped[key] = True
        return True
    return False


def _bankroll_reset_for_tests() -> None:
    """Clear the in-memory EMA state. Tests use this to isolate runs."""
    _bankroll_ema_baseline.clear()
    _bankroll_ema_baseline_active.clear()
    _bankroll_ema_last_update.clear()
    _bankroll_circuit_tripped.clear()


# =====================================================================
# Safe-close direction concentration window
# (WARP/R00T/safe-close-direction-limit, Lane 4/5 Polybot directive)
# =====================================================================
#
# Per-user, per-side rolling 1h log of accepted safe_close entries. Used
# to skip new safe_close entries on a side the user is already
# over-concentrated on — defends against the trending-market case where
# the dynamic `fav_side = "YES" if yes_ask > no_ask else "NO"` filter
# repeatedly leans the same direction across many candles (e.g. BTC
# downtrend Dec 14-18 2025 produced 55.9% NO win-rate in Polybot
# research, which is sample-period bias, not edge).
#
# Per-user — concentration is a single-user risk, not a global one.
# In-memory — the window is 1h, eviction is O(n_entries_for_user); a
# crash drops the counter (acceptable: worst case is a single extra
# entry before the limiter rebuilds, much smaller than a stuck DB hit
# per scan tick).
_SAFE_CLOSE_DIRECTION_WINDOW_SEC = 3600.0
_safe_close_direction_log: dict[tuple[str, str], list[float]] = {}


def _safe_close_recent_count(user_id: str, side: str, now_ts: float) -> int:
    """Return the count of recorded safe_close entries for (user, side)
    within the last `_SAFE_CLOSE_DIRECTION_WINDOW_SEC` seconds. Prunes
    expired entries in-place as a side effect; deletes the dict key
    entirely if pruning empties the list (memory hygiene — avoids
    monotonic growth of the dict from inactive-user keys)."""
    key = (str(user_id), side.upper())
    entries = _safe_close_direction_log.get(key)
    if entries is None:
        return 0
    cutoff = now_ts - _SAFE_CLOSE_DIRECTION_WINDOW_SEC
    if entries and entries[0] < cutoff:
        entries[:] = [t for t in entries if t >= cutoff]
    if not entries:
        del _safe_close_direction_log[key]
        return 0
    return len(entries)


def _safe_close_record_entry(user_id: str, side: str, now_ts: float) -> None:
    """Append a timestamp to the (user, side) window. Called on accepted
    paper-mode safe_close entries (skip on duplicate / rejected)."""
    key = (str(user_id), side.upper())
    _safe_close_direction_log.setdefault(key, []).append(now_ts)


def _safe_close_reset_for_tests() -> None:
    """Clear the in-memory window. Tests use this to isolate runs."""
    _safe_close_direction_log.clear()


@dataclass
class ScanTelemetry:
    """Accumulates per-scan-run observability counts for the scan_runs table."""

    users_evaluated: int = 0
    markets_seen: int = 0
    markets_eligible: int = 0
    candidates_emitted: int = 0
    risk_approved: int = 0
    risk_rejected: int = 0
    paper_orders_created: int = 0
    positions_created: int = 0
    snapshots_written: int = 0
    skip_breakdown: dict[str, int] = field(default_factory=dict)
    zero_reason_breakdown: dict[str, int] = field(default_factory=dict)
    rejection_breakdown: dict[str, int] = field(default_factory=dict)

    def record_skip(self, reason: str) -> None:
        self.skip_breakdown[reason] = self.skip_breakdown.get(reason, 0) + 1

    def record_zero_reason(self, strategy: str, reason: str) -> None:
        key = f"{strategy}:{reason}"
        self.zero_reason_breakdown[key] = self.zero_reason_breakdown.get(key, 0) + 1

    def record_rejection(self, step: int | None, reason: str) -> None:
        key = f"step_{step}_{reason}" if step is not None else f"unknown_{reason}"
        self.rejection_breakdown[key] = self.rejection_breakdown.get(key, 0) + 1
        self.risk_rejected += 1

    def record_approved(self) -> None:
        self.risk_approved += 1
        self.paper_orders_created += 1
        self.positions_created += 1


# Global operator on/off switch (migration 067 `strategies` table). FAIL-SAFE:
# a strategy is ON unless its name appears here (set to disabled). Refreshed
# once per scan tick; an empty set = nothing disabled = no behaviour change.
_GLOBALLY_DISABLED_STRATEGIES: frozenset[str] = frozenset()


async def _refresh_disabled_strategies() -> None:
    """Reload the globally-disabled strategy set from the `strategies` table.

    Never raises — on any error the previous set is kept (fail-safe: a DB blip
    must not silently disable or enable strategies). Called once per tick.
    """
    global _GLOBALLY_DISABLED_STRATEGIES
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name FROM strategies WHERE enabled = FALSE"
            )
        _GLOBALLY_DISABLED_STRATEGIES = frozenset(str(r["name"]) for r in rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("strategy_toggle_refresh_failed", error=str(exc))


def _preset_allows(active_preset: str | None, strategy_name: str) -> bool:
    """Return True if user's active_preset permits signals from strategy_name.

    A globally-disabled strategy (operator Admin toggle) is never allowed,
    regardless of preset.
    """
    if strategy_name in _GLOBALLY_DISABLED_STRATEGIES:
        return False
    return strategy_name in _PRESET_ALLOWED.get(active_preset, _LIB_STRATEGY_NAMES)


def _coerce_jsonb(val: object, fallback: dict | list | None = None) -> dict | list:
    """asyncpg may return JSONB columns as str — coerce to dict/list.

    Narrows to the same shape as ``fallback`` (dict or list). JSON scalars
    (e.g. ``'"balanced"'`` → string, ``'1'`` → int) return ``fallback`` so a
    malformed user_settings.strategy_params row cannot leak a string into
    ``strategy.initialize()`` and trigger ``ValueError: dictionary update
    sequence element #0 has length 1; 2 is required``.
    """
    if fallback is None:
        fallback = {}
    expected_type = type(fallback)  # dict or list
    if val is None:
        return fallback
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return fallback
        return parsed if isinstance(parsed, expected_type) else fallback
    if isinstance(val, expected_type):
        return val
    return fallback

# Module-level TradeEngine singleton — stateless; safe to share across ticks.
_engine: TradeEngine = TradeEngine()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_enrolled_users() -> list[dict[str, Any]]:
    """Active users enrolled in signal_following strategy with auto_trade_on."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                u.id                     AS user_id,
                u.telegram_user_id,
                u.role,
                u.auto_trade_on,
                u.paused,
                COALESCE(w.balance_usdc, 0)   AS balance_usdc,
                COALESCE((SELECT SUM(p.size_usdc) FROM positions p
                          WHERE p.user_id = u.id AND p.status = 'open'), 0) AS open_cost_usdc,
                COALESCE(s.risk_profile, 'balanced') AS risk_profile,
                COALESCE(s.trading_mode, 'paper')    AS trading_mode,
                COALESCE(s.live_capital_cap_usdc, 0) AS live_capital_cap_usdc,
                s.tp_pct,
                s.sl_pct,
                s.daily_loss_override,
                s.max_drawdown_pct,
                us.weight                AS capital_allocation_pct,
                COALESCE(urp.profile_name, s.risk_profile, 'balanced') AS resolved_profile,
                s.active_preset,
                s.selected_timeframe,
                s.selected_assets,
                s.max_per_trade_mode,
                s.max_per_trade_usdc,
                s.max_per_trade_pct,
                COALESCE(s.min_liquidity, 0)         AS min_liquidity_threshold,
                COALESCE(s.strategy_params, '{}'::jsonb)      AS strategy_params,
                COALESCE(s.category_filters, ARRAY[]::text[]) AS category_filters
            FROM user_strategies us
            JOIN users          u   ON u.id  = us.user_id
            JOIN wallets        w   ON w.user_id = u.id
            JOIN user_settings  s   ON s.user_id = u.id
            LEFT JOIN user_risk_profile urp ON urp.user_id = u.id
            WHERE us.strategy_name = $1
              AND us.enabled        = TRUE
              AND u.auto_trade_on   = TRUE
              AND u.paused          = FALSE
              -- Global operator on/off (migration 067). FAIL-SAFE: ON unless a
              -- row explicitly marks this strategy disabled.
              AND NOT EXISTS (
                    SELECT 1 FROM strategies st
                     WHERE st.name = us.strategy_name AND st.enabled = FALSE
              )
            """,
            _STRATEGY_NAME,
        )
    return [dict(r) for r in rows]


async def _load_market(market_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM markets WHERE id = $1",
            market_id,
        )
    return dict(row) if row else None


def _coerce_str_list(val: Any) -> list[str]:
    """Gamma list fields (outcomePrices, clobTokenIds) may arrive as a JSON
    string or a real list. Return a list of strings, or [] on failure."""
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (ValueError, TypeError):
            return []
    if isinstance(val, list):
        return [str(x) for x in val]
    return []


async def _upsert_crypto_window_markets(markets: list[dict[str, Any]]) -> None:
    """Upsert live crypto candle markets into the markets table.

    The signal pipeline's _load_market gate requires the candidate's market to
    exist locally, but market_sync (Heisenberg, min_volume>=50k) never pulls
    these continuously-created micro candle markets — so close_sweep/scalper
    candidates were skipped as ``skipped_market_not_synced``. Upserting them here
    (keyed by condition_id, the markets PK) makes the candidate resolvable and
    carries the CLOB token ids the trade engine needs. Idempotent ON CONFLICT.
    """
    if not markets:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        for m in markets:
            try:
                condition_id = str(m.get("conditionId") or m.get("condition_id") or "")
                if not condition_id:
                    continue
                slug = str(m.get("slug") or "")[:80]
                question = str(m.get("question") or m.get("title") or "")[:500]
                prices = _coerce_str_list(m.get("outcomePrices"))
                tokens = _coerce_str_list(m.get("clobTokenIds"))

                def _f(v: Any, d: float) -> float:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return d
                yes_price = _f(prices[0] if prices else None, 0.5)
                no_price = _f(prices[1] if len(prices) > 1 else None, 0.5)
                yes_token = tokens[0] if tokens else None
                no_token = tokens[1] if len(tokens) > 1 else None
                liquidity = _f(m.get("liquidity"), 0.0)
                end_iso = m.get("endDate") or m.get("end_date_iso")
                resolution_at = None
                if end_iso:
                    try:
                        resolution_at = datetime.fromisoformat(
                            str(end_iso).replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        resolution_at = None
                await conn.execute(
                    """
                    INSERT INTO markets
                        (id, slug, question, category, status,
                         yes_price, no_price, yes_token_id, no_token_id,
                         liquidity_usdc, resolution_at, condition_id, is_demo, synced_at)
                    VALUES ($1,$2,$3,'crypto','active',$4,$5,$6,$7,$8,$9,$1,FALSE,NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        slug           = EXCLUDED.slug,
                        question       = EXCLUDED.question,
                        status         = 'active',
                        yes_price      = EXCLUDED.yes_price,
                        no_price       = EXCLUDED.no_price,
                        yes_token_id   = EXCLUDED.yes_token_id,
                        no_token_id    = EXCLUDED.no_token_id,
                        liquidity_usdc = EXCLUDED.liquidity_usdc,
                        resolution_at  = EXCLUDED.resolution_at,
                        synced_at      = NOW()
                    """,
                    condition_id, slug, question,
                    yes_price, no_price, yes_token, no_token,
                    liquidity, resolution_at,
                )
            except Exception as exc:
                logger.warning("crypto_window_upsert_failed", error=str(exc))



async def _publication_already_queued(user_id: UUID, publication_id: UUID) -> bool:
    """Return True when (user_id, publication_id) already in execution_queue."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM execution_queue "
            " WHERE user_id = $1 AND publication_id = $2"
            "   AND status IN ('executed', 'failed')",
            user_id, publication_id,
        )
    return row is not None


async def _load_stale_queued_row(
    user_id: UUID,
    publication_id: UUID,
) -> dict[str, Any] | None:
    """Return the stale status='queued' row for crash-recovery resume, or None.

    A 'queued' row means a prior tick inserted the queue entry and approved
    the gate but crashed before router_execute completed.  The row must be
    resumed without re-running the gate because: (a) gate step 10 rejects
    the same idempotency_key for 30 min, and (b) gate step 9 rejects the
    original signal after the 4h staleness window (SIGNAL_STALE_SECONDS=14400).
    Current market prices are re-fetched at resume time, so stale entry prices
    are not a concern on this path.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT market_id, side, final_size_usdc, suggested_size_usdc, "
            "       idempotency_key, chosen_mode "
            "  FROM execution_queue "
            " WHERE user_id = $1 AND publication_id = $2 AND status = 'queued'",
            user_id, publication_id,
        )
    return dict(row) if row else None


async def _fetch_market_inventory_for_override(
    user_id: UUID, market_id: str,
):
    """Fetch the per-market inventory for the safe-close override gate.

    Wraps pool acquisition + `compute_market_inventory` + error
    handling so the gate path stays small and tests have a single
    patch target (rather than mocking the whole connection pool).
    Returns ``None`` on any failure — the caller treats None the
    same as "no inventory data; do not override".
    """
    try:
        from ...domain.strategy.inventory import compute_market_inventory
        pool = get_pool()
        async with pool.acquire() as conn:
            return await compute_market_inventory(conn, user_id, market_id)
    except Exception as exc:
        logger.warning(
            "safe_close_inventory_compute_failed",
            error=str(exc),
            market_id=market_id,
        )
        return None


_FAST_TOPUP_ELIGIBLE_PRESETS: frozenset[str] = frozenset({"flip_hunter", "safe_close"})
# Extended set when CLOSE_SWEEP_DUAL_LEG_ENABLED is on. close_sweep is
# tracked separately so an operator can enable D-3 (safe_close +
# flip_hunter top-up) without enabling D-4 (close_sweep dual-leg), or
# vice versa. See _resolve_eligible_topup_presets below for the
# runtime resolution.
_CLOSE_SWEEP_DUAL_LEG_PRESETS: frozenset[str] = frozenset({"close_sweep"})


def _resolve_eligible_topup_presets(cfg: Any) -> frozenset[str]:
    """Compute the runtime-eligible preset set from the two flags.

    Returns the union of base D-3 presets (when
    ``FLIP_HUNTER_FAST_TOPUP_ENABLED``) and D-4 presets (when
    ``CLOSE_SWEEP_DUAL_LEG_ENABLED``). When neither flag is on the
    result is empty and ``_maybe_fire_fast_topup`` bails immediately.

    Defensive: a ``None`` config (e.g. from a config-init failure
    upstream) returns an empty frozenset rather than raising
    ``AttributeError`` — the caller is expected to log + bail
    on the empty result, not crash the scan loop.

    Kept as a small named helper so tests can pin the resolution
    contract without duplicating the boolean-soup in the hot path.
    """
    if cfg is None:
        return frozenset()
    presets: set[str] = set()
    if getattr(cfg, "FLIP_HUNTER_FAST_TOPUP_ENABLED", False):
        presets |= _FAST_TOPUP_ELIGIBLE_PRESETS
    if getattr(cfg, "CLOSE_SWEEP_DUAL_LEG_ENABLED", False):
        presets |= _CLOSE_SWEEP_DUAL_LEG_PRESETS
    return frozenset(presets)


async def _maybe_fire_fast_topup(
    *,
    row: dict[str, Any],
    market: dict[str, Any],
    just_filled_side: str,
    just_filled_size_usdc: Decimal,
    log,
) -> None:
    """Optionally fire an opposite-leg top-up after a successful entry.

    Implements Polybot directive 1.5 + 1.3.2 (fast top-up after partial
    fill). For our paper engine fills are always complete so the
    "partial fill" condition collapses to "after every successful
    entry" — the helper recomputes inventory, identifies the lagging
    leg, and synthesises a TradeSignal for it. Risk gate inside
    TradeEngine.execute applies (Kelly, position caps, daily loss).

    Default OFF; controlled by `config.FLIP_HUNTER_FAST_TOPUP_ENABLED`.
    Scoped to users whose `active_preset` is `safe_close` or
    `flip_hunter`. Per-(user, market) cooldown prevents the same pair
    spinning top-ups within `FAST_TOPUP_COOLDOWN_SECONDS`.

    Returns None on every path (fire-and-forget from the caller's
    perspective). Exceptions are caught + logged — a top-up failure
    must never crash the originating entry's success branch.
    """
    try:
        from ...config import get_settings as _gs_ft
        _cfg = _gs_ft()
        _eligible_presets = _resolve_eligible_topup_presets(_cfg)
        if not _eligible_presets:
            # Neither D-3 (FLIP_HUNTER_FAST_TOPUP_ENABLED) nor D-4
            # (CLOSE_SWEEP_DUAL_LEG_ENABLED) is on. Fully bypass.
            return
        preset = str(row.get("active_preset") or "").lower()
        if preset not in _eligible_presets:
            return
        _min_usdc = float(_cfg.FAST_TOPUP_MIN_USDC)
        _cooldown = float(_cfg.FAST_TOPUP_COOLDOWN_SECONDS)
    except Exception as exc:
        log.warning("fast_topup_config_read_failed", error=str(exc))
        return

    user_id = UUID(str(row["user_id"]))
    market_id = str(market.get("id") or "")
    if not market_id:
        return

    # Cooldown check — per-(user, market). Skip without DB hit.
    key = _fast_topup_key(user_id, market_id)
    last_at = _fast_topup_last_at.get(key, 0.0)
    now_mono = _time.monotonic()
    if (now_mono - last_at) < _cooldown:
        log.info(
            "fast_topup_skipped",
            reason="cooldown",
            market_id=market_id,
            cooldown_remaining_sec=round(_cooldown - (now_mono - last_at), 2),
        )
        return

    # Compute inventory AFTER the lead entry has committed — includes
    # the position just created.
    inventory = await _fetch_market_inventory_for_override(user_id, market_id)
    if inventory is None or inventory.is_empty:
        return
    imb = float(inventory.imbalance_usdc)
    if abs(imb) < _min_usdc:
        log.info(
            "fast_topup_skipped",
            reason="below_threshold",
            market_id=market_id,
            imbalance_usdc=round(imb, 4),
            threshold_usdc=_min_usdc,
        )
        return

    # Lagging side: imb > 0 → YES-heavy → lag is NO.
    lagging_side_upper = "NO" if imb > 0 else "YES"
    lagging_side_lower = lagging_side_upper.lower()
    just_filled_lower = str(just_filled_side).lower()
    if just_filled_lower == lagging_side_lower:
        # The lead entry already targeted the lagging leg — nothing
        # to top up. Possible when the imbalance override flipped the
        # side or when the strategy just happened to pick lagging.
        return

    # Choose top-up size: |imbalance| capped to the lead entry size so
    # we never over-shoot the original commitment. Subject to the
    # engine's Kelly + per-trade caps downstream.
    topup_usdc = min(Decimal(str(abs(imb))), just_filled_size_usdc)
    if topup_usdc <= Decimal("0"):
        return

    # Resolve a fill price for the lagging leg: prefer the live mark
    # so the top-up reflects current orderbook state. Fall back to
    # 1 - (lead price) when the live fetch fails (binary market
    # invariant). The TradeEngine risk gate will sanity-check.
    try:
        _topup_price = await get_live_market_price(market_id, lagging_side_lower)
    except Exception as exc:
        log.warning(
            "fast_topup_price_fetch_failed", error=str(exc),
            market_id=market_id, side=lagging_side_lower,
        )
        _topup_price = None
    if _topup_price is None or not (0.0 < _topup_price < 1.0):
        # Binary settlement invariant: YES + NO = 1. Use the
        # market_row's stored prices as a defensive fallback.
        _yes_p = float(market.get("yes_price") or 0.5)
        _no_p = float(market.get("no_price") or (1.0 - _yes_p))
        _topup_price = _no_p if lagging_side_lower == "no" else _yes_p

    # Synthesise an idempotency key — distinct from the lead entry's
    # so the engine's duplicate guard doesn't reject the top-up as a
    # double-execute.
    topup_idem = f"fast_topup:{key}:{int(now_mono * 1000)}"

    # Build a TradeSignal directly. Bypassing _build_trade_signal +
    # _process_candidate gates is deliberate: the top-up is reactive,
    # not predictive (TOB freshness / complete-set edge / safe-close
    # direction limit don't apply). The 13-step risk gate inside
    # TradeEngine.execute still runs.
    try:
        from ..trade_engine import TradeSignal
        signal = TradeSignal(
            user_id=user_id,
            telegram_user_id=int(row["telegram_user_id"]),
            role=str(row.get("role") or "user"),
            auto_trade_on=bool(row.get("auto_trade_on", False)),
            paused=bool(row.get("paused", False)),
            market_id=market_id,
            market_question=str(market.get("question") or "") or None,
            yes_token_id=market.get("yes_token_id"),
            no_token_id=market.get("no_token_id"),
            side=lagging_side_lower,
            proposed_size_usdc=topup_usdc,
            price=_topup_price,
            market_liquidity=float(market.get("liquidity_usdc") or 0.0),
            market_status=str(market.get("status") or "active"),
            idempotency_key=topup_idem,
            strategy_type="fast_topup",
            risk_profile=str(row.get("resolved_profile") or "balanced"),
            trading_mode=str(row.get("trading_mode") or "paper"),
            signal_ts=datetime.now(timezone.utc),
            tp_pct=float(row["tp_pct"]) if row.get("tp_pct") is not None else None,
            sl_pct=float(row["sl_pct"]) if row.get("sl_pct") is not None else None,
            daily_loss_override=(
                float(row["daily_loss_override"])
                if row.get("daily_loss_override") is not None
                else None
            ),
            user_min_liquidity=float(row.get("min_liquidity_threshold") or 0.0),
            max_drawdown_pct=(
                float(row["max_drawdown_pct"])
                if row.get("max_drawdown_pct") is not None
                else None
            ),
            active_preset=preset,
            live_capital_cap_usdc=float(row.get("live_capital_cap_usdc") or 0.0),
        )
    except Exception as exc:
        log.warning("fast_topup_signal_build_failed", error=str(exc))
        return

    try:
        result = await _engine.execute(signal)
    except Exception as exc:
        log.warning(
            "fast_topup_engine_failed", error=str(exc),
            market_id=market_id, side=lagging_side_lower,
        )
        return

    # Stamp cooldown regardless of approval — a rejected top-up still
    # tried to fire; we don't want the rejection feedback loop to
    # immediately re-trigger the same attempt on the next inventory
    # check.
    _fast_topup_last_at[key] = now_mono

    if result.approved:
        log.info(
            "scan_outcome",
            outcome="fast_topup_fired",
            market_id=market_id,
            side=lagging_side_lower,
            size_usdc=str(topup_usdc),
            price=_topup_price,
            imbalance_usdc=round(imb, 4),
            preset=preset,
        )
    else:
        log.info(
            "scan_outcome",
            outcome="fast_topup_rejected",
            market_id=market_id,
            side=lagging_side_lower,
            reason=result.rejection_reason,
            failed_step=result.failed_gate_step,
        )


async def _has_open_position_for_side(
    user_id: UUID, market_id: str, side: str,
) -> bool:
    """Side-aware variant of `_has_open_position_for_market`.

    Used ONLY by the safe-close imbalance override path
    (WARP/R00T/safe-close-imbalance-override). When the override fires,
    the candidate is rebalancing toward the lagging leg so the broad
    market-wide dedup is wrong — it would block the rebalance even
    though the opposite leg is what we actually want to enter.

    Returns True if the user already holds a live position on
    ``(market_id, side)``. Does NOT include the 24h closed-position
    window — the override is specifically opening a NEW opposite-side
    position, and a recently-closed same-side position is no reason
    to block.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM positions
             WHERE user_id = $1 AND market_id = $2
               AND LOWER(side) = $3
               AND status IN ('open', 'pending_settlement')
             LIMIT 1
            """,
            user_id,
            market_id,
            side.lower(),
        )
    return row is not None


async def _has_open_position_for_market(user_id: UUID, market_id: str) -> bool:
    """Return True when the user has an open OR recently closed (24h) position on this market.

    Runs before the risk gate so it short-circuits without creating a risk_log
    entry or idempotency_key record. Closes the race window between two
    concurrent scan ticks that both pass gate step 10 (orders-table dedup)
    before either has committed its position row — positions is the
    authoritative source because it is committed in the same atomic transaction
    as the order row.

    The 24h closed-position window prevents the scanner from immediately
    reopening the same market after a TP/SL/manual close within the same day.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM positions
             WHERE user_id = $1 AND market_id = $2
               AND (
                   status IN ('open', 'pending_settlement')
                   OR (status = 'closed' AND closed_at >= NOW() - INTERVAL '24 hours')
               )
            """,
            user_id, market_id,
        )
    return row is not None


async def _insert_execution_queue(
    *,
    user_id: UUID,
    strategy_name: str,
    market_id: str,
    side: str,
    publication_id: UUID | None,
    suggested_size_usdc: Decimal,
    final_size_usdc: Decimal,
    idempotency_key: str,
    chosen_mode: str,
) -> bool:
    """Insert execution queue entry.  Returns True on new insert, False on conflict."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO execution_queue
                (user_id, strategy_name, market_id, side, publication_id,
                 suggested_size_usdc, final_size_usdc, idempotency_key,
                 chosen_mode, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'queued')
            ON CONFLICT (user_id, publication_id) WHERE publication_id IS NOT NULL
            DO NOTHING
            RETURNING id
            """,
            user_id, strategy_name, market_id, side, publication_id,
            suggested_size_usdc, final_size_usdc, idempotency_key, chosen_mode,
        )
    return row is not None


async def _mark_executed(
    user_id: UUID,
    publication_id: UUID | None,
    idempotency_key: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE execution_queue
               SET status = 'executed', executed_at = NOW()
             WHERE user_id = $1
               AND ($2::uuid IS NULL OR publication_id = $2)
               AND idempotency_key = $3
               AND status = 'queued'
            """,
            user_id, publication_id, idempotency_key,
        )


async def _mark_failed(
    user_id: UUID,
    publication_id: UUID | None,
    idempotency_key: str,
    error: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE execution_queue
               SET status = 'failed', error_detail = $4, executed_at = NOW()
             WHERE user_id = $1
               AND ($2::uuid IS NULL OR publication_id = $2)
               AND idempotency_key = $3
               AND status = 'queued'
            """,
            user_id, publication_id, idempotency_key, error[:500],
        )


# ---------------------------------------------------------------------------
# Scan run DB helpers (telemetry)
# ---------------------------------------------------------------------------


async def _insert_scan_run(
    run_id: str,
    *,
    strategies_loaded: int,
    live_trading: bool,
    mode: str,
) -> None:
    """Insert a scan_runs row at tick start. Non-fatal on error."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scan_runs (id, strategies_loaded, live_trading, mode)
                VALUES ($1::uuid, $2, $3, $4)
                ON CONFLICT (id) DO NOTHING
                """,
                run_id, strategies_loaded, live_trading, mode,
            )
    except Exception as exc:
        logger.warning("scan_run_insert_failed", run_id=run_id, error=str(exc))


async def _finish_scan_run(run_id: str, tel: ScanTelemetry) -> None:
    """UPDATE the scan_runs row at tick end with full telemetry. Non-fatal on error."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scan_runs SET
                    finished_at           = NOW(),
                    users_evaluated       = $2,
                    markets_seen          = $3,
                    markets_eligible      = $4,
                    candidates_emitted    = $5,
                    risk_approved         = $6,
                    risk_rejected         = $7,
                    paper_orders_created  = $8,
                    positions_created     = $9,
                    snapshots_written     = $10,
                    skip_breakdown        = $11::jsonb,
                    zero_reason_breakdown = $12::jsonb,
                    rejection_breakdown   = $13::jsonb
                WHERE id = $1::uuid
                """,
                run_id,
                tel.users_evaluated,
                tel.markets_seen,
                tel.markets_eligible,
                tel.candidates_emitted,
                tel.risk_approved,
                tel.risk_rejected,
                tel.paper_orders_created,
                tel.positions_created,
                tel.snapshots_written,
                json.dumps(tel.skip_breakdown),
                json.dumps(tel.zero_reason_breakdown),
                json.dumps(tel.rejection_breakdown),
            )
    except Exception as exc:
        logger.warning("scan_run_finish_failed", run_id=run_id, error=str(exc))


async def fetch_latest_scan_run() -> dict[str, Any] | None:
    """Return the most recent ``scan_runs`` row as a dict, or None.

    Read-only observability accessor for the real feed-eval engine (this
    module). The Telegram operator panel reads this instead of the legacy
    ``run_signal_scan`` job_runs row, which only loads copy_trade and always
    reports zero candidates. Mirrors the column set served by
    ``api/admin.py`` GET /scan/last.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, started_at, finished_at,
                       users_evaluated, markets_seen, markets_eligible,
                       strategies_loaded, candidates_emitted,
                       risk_approved, risk_rejected,
                       paper_orders_created, positions_created, snapshots_written,
                       skip_breakdown, zero_reason_breakdown, rejection_breakdown,
                       mode, live_trading
                  FROM scan_runs
                 ORDER BY started_at DESC
                 LIMIT 1
                """
            )
    except Exception as exc:
        logger.warning("scan_run_fetch_latest_failed", error=str(exc))
        return None
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def _build_user_context(row: dict[str, Any]) -> UserContext:
    _alloc = row.get("capital_allocation_pct")
    allocation = float(_alloc if _alloc is not None else 0.10)
    allocation = max(0.0, min(1.0, allocation))
    sub_account_id = str(row.get("sub_account_id") or row["user_id"])
    _tf = row.get("selected_timeframe")
    _assets = tuple(_filter_monitor_only_assets(row.get("selected_assets")))
    balance = float(row.get("balance_usdc") or 0.0)
    # Equity = free balance + capital already deployed in open positions (cost
    # basis). Sizing is based on equity so the deployable pool reflects the
    # whole account rather than only the idle cash.
    equity = balance + float(row.get("open_cost_usdc") or 0.0)
    return UserContext(
        user_id=str(row["user_id"]),
        sub_account_id=sub_account_id,
        risk_profile=str(row.get("resolved_profile") or "balanced"),
        capital_allocation_pct=allocation,
        available_balance_usdc=balance,
        equity_usdc=equity,
        selected_timeframe=str(_tf) if _tf else None,
        selected_assets=_assets,
        max_per_trade_mode=str(row.get("max_per_trade_mode") or "auto"),
        max_per_trade_usdc=(
            float(row["max_per_trade_usdc"]) if row.get("max_per_trade_usdc") is not None else None
        ),
        max_per_trade_pct=(
            float(row["max_per_trade_pct"]) if row.get("max_per_trade_pct") is not None else None
        ),
    )


def _build_market_filters(profile: str, row: dict | None = None) -> MarketFilters:
    # Resolution-horizon and liquidity floor are derived from the user's risk
    # profile (PROFILES in domain/risk/constants). Conservative=7d / Balanced=30d
    # / Aggressive=90d. User settings (min_liquidity_threshold, category_filters)
    # override the profile defaults when set — this is what the WebTrader
    # Market Filter UI saves to user_settings.
    preset = PROFILES.get((profile or "balanced").lower(), PROFILES["balanced"])

    # User-configured liquidity floor overrides profile default when > 0.
    user_min_liq = float((row or {}).get("min_liquidity_threshold") or 0.0)
    min_liq = user_min_liq if user_min_liq > 0 else float(preset["min_liquidity"])

    # User-configured category filter overrides empty default when set.
    user_cats = list((row or {}).get("category_filters") or [])

    return MarketFilters(
        categories=user_cats,
        min_liquidity=min_liq,
        max_time_to_resolution_days=int(preset["max_days"]),
        blacklisted_market_ids=[],
    )


def _build_idempotency_key(
    user_id: UUID,
    market_id: str,
    side: str,
    publication_id: UUID | None,  # retained for signature compat; no longer in hash
) -> str:
    # UTC calendar day prevents same-day re-entry on the same market.
    # Without this, distinct publication_ids for the same market produce distinct
    # keys, each passing the 30-min gate independently → duplicate open positions.
    # Cross-day re-entry is intentional — new trading day = new opportunity.
    # Explicit UTC (not date.today()) keeps rotation stable across all host timezones.
    raw = f"{user_id}:{market_id}:{side}:{datetime.now(timezone.utc).date().isoformat()}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"sf:{digest}"


def _build_trade_signal(
    *,
    row: dict[str, Any],
    cand: SignalCandidate,
    market: dict[str, Any],
    idempotency_key: str,
    live_price_override: float | None = None,
) -> TradeSignal:
    """Build a typed TradeSignal from scan-loop data for TradeEngine.execute()."""
    _side = cand.side.lower()
    if live_price_override is not None:
        # Use live price from Gamma/CLOB — same source as exit_watcher.
        # This keeps paper entry consistent with exit evaluation so
        # return_pct reflects real market movement, not a DB cache gap.
        # is-not-None (not > 0) so a live price of exactly 0.0 is honoured.
        _price = live_price_override
    else:
        # Fallback: cached DB price when live fetch unavailable.
        if _side == "no":
            _primary, _fallback = market.get("no_price"), market.get("yes_price")
        else:
            _primary, _fallback = market.get("yes_price"), market.get("no_price")
        _price = float(
            _primary if _primary is not None else (_fallback if _fallback is not None else 0.5)
        )
    # Use CLOB-derived liquidity when the candidate carries it (late_entry_v3
    # computes live bid depth from both token books). Candle markets have
    # near-zero Gamma liquidity_usdc in the DB, which causes gate 11 to reject
    # every candidate. The CLOB book depth is the real available liquidity.
    _clob_liq = cand.metadata.get("clob_liquidity")
    _market_liquidity = (
        float(_clob_liq)
        if _clob_liq is not None and float(_clob_liq) > 0
        else float(market.get("liquidity_usdc") or 0.0)
    )

    # Bankroll dynamic sizing multiplier
    # (WARP/R00T/bankroll-dynamic-sizing, Lane 5/5).
    # Scales the candidate's base size by the user's bankroll deviation
    # from its EMA-smoothed baseline. Fail-safe = 1.0 (no scaling) when
    # the knob is off, the user has no baseline yet (first observation),
    # the current balance is non-positive / non-finite, or the config
    # read raises. Risk gate (Kelly etc.) inside the engine still
    # applies to the scaled value, so position caps remain authoritative.
    _base_size = Decimal(str(cand.suggested_size_usdc))
    _proposed_size = _base_size
    try:
        from ...config import get_settings as _gs_bankroll
        _cfg_b = _gs_bankroll()
        if getattr(_cfg_b, "BANKROLL_DYNAMIC_SIZING_ENABLED", False):
            _mult = _bankroll_multiplier(
                str(row["user_id"]),
                float(row.get("balance_usdc") or 0.0),
                multiplier_min=float(_cfg_b.BANKROLL_MULTIPLIER_MIN),
                multiplier_max=float(_cfg_b.BANKROLL_MULTIPLIER_MAX),
                ema_alpha=float(_cfg_b.BANKROLL_EMA_ALPHA),
                min_update_interval_sec=float(
                    getattr(_cfg_b, "BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC", 5.0)
                ),
            )
            if _mult != 1.0:
                _proposed_size = (
                    _base_size * Decimal(str(_mult))
                ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    except Exception as exc:
        # AGENTS.md hard rule: zero silent failures. Log the diagnostic
        # context and fall back to the unscaled base size. `logger`
        # (not `log`) — _build_trade_signal is module-level scope, the
        # per-call `log = logger.bind(...)` only exists in
        # _process_candidate.
        logger.warning(
            "bankroll_dynamic_sizing_failed",
            error=str(exc),
            fallback_size_usdc=str(_base_size),
        )

    return TradeSignal(
        user_id=UUID(str(row["user_id"])),
        telegram_user_id=int(row["telegram_user_id"]),
        role=str(row.get("role") or "user"),
        auto_trade_on=bool(row["auto_trade_on"]),
        paused=bool(row["paused"]),
        market_id=cand.market_id,
        market_question=str(market.get("question") or ""),
        yes_token_id=market.get("yes_token_id"),
        no_token_id=market.get("no_token_id"),
        side=_side,
        proposed_size_usdc=_proposed_size,
        price=_price,
        market_liquidity=_market_liquidity,
        market_status=str(market.get("status") or ""),
        idempotency_key=idempotency_key,
        strategy_type=cand.strategy_name,
        risk_profile=str(row.get("resolved_profile") or "balanced"),
        trading_mode=str(row.get("trading_mode") or "paper"),
        signal_ts=cand.signal_ts,
        edge_bps=None,
        tp_pct=float(row["tp_pct"]) if row.get("tp_pct") is not None else None,
        sl_pct=float(row["sl_pct"]) if row.get("sl_pct") is not None else None,
        daily_loss_override=(
            float(row["daily_loss_override"])
            if row.get("daily_loss_override") is not None
            else None
        ),
        user_min_liquidity=float(row.get("min_liquidity_threshold") or 0.0),
        max_drawdown_pct=(
            float(row["max_drawdown_pct"])
            if row.get("max_drawdown_pct") is not None
            else None
        ),
        active_preset=str(row["active_preset"]) if row.get("active_preset") else None,
        # Per-user live capital cap (Axis #3, migration 064). Missing column
        # on a stale schema → defaults to 0 → gate step 15 rejects live mode
        # (safe-by-default).
        live_capital_cap_usdc=float(row.get("live_capital_cap_usdc") or 0.0),
    )


# ---------------------------------------------------------------------------
# Per-candidate processing
# ---------------------------------------------------------------------------


async def _process_candidate(
    row: dict[str, Any],
    cand: SignalCandidate,
    telemetry: ScanTelemetry | None = None,
) -> None:
    user_id = UUID(str(row["user_id"]))
    side = cand.side.lower()  # execution engines compare lowercase; normalize once here
    pub_id_raw = cand.metadata.get("publication_id")
    pub_uuid: UUID | None = None
    if pub_id_raw:
        try:
            pub_uuid = UUID(str(pub_id_raw))
        except (TypeError, ValueError):
            pass

    log = logger.bind(
        user_id=str(user_id),
        market_id=cand.market_id,
        side=side,
        strategy=_STRATEGY_NAME,
        publication_id=str(pub_uuid) if pub_uuid else None,
    )

    # 0. Crash-recovery resume — a prior tick inserted a 'queued' row but
    #    crashed before the paper engine completed. Re-running the gate would
    #    fail at step 10 (idempotency_key already recorded for 30 min) or
    #    step 9 (signal stale after 4h / SIGNAL_STALE_SECONDS=14400), so router_execute is called
    #    directly from the stored row. This is the ONLY direct router call
    #    in this module; all normal execution paths go through TradeEngine.
    if pub_uuid is not None:
        try:
            stale = await _load_stale_queued_row(user_id, pub_uuid)
        except Exception as exc:
            log.warning("stale_queue_check_failed", error=str(exc))
            stale = None
        if stale is not None:
            if await kill_switch_is_active():
                log.info("scan_outcome", outcome="skipped_kill_switch")
                if telemetry is not None:
                    telemetry.record_skip("skipped_kill_switch")
                return  # leave row as 'queued' — retry when switch is off
            stale_market = await _load_market(stale["market_id"])
            if stale_market is None:
                log.info("scan_outcome", outcome="skipped_market_not_synced")
                if telemetry is not None:
                    telemetry.record_skip("skipped_market_not_synced")
                return
            _stale_side = str(stale["side"])
            if _stale_side == "no":
                _sp, _sf = stale_market.get("no_price"), stale_market.get("yes_price")
            else:
                _sp, _sf = stale_market.get("yes_price"), stale_market.get("no_price")
            _stale_price = float(
                _sp if _sp is not None else (_sf if _sf is not None else 0.5)
            )
            _stale_idem = str(stale["idempotency_key"])
            _stale_size = Decimal(str(stale["final_size_usdc"]))
            _tp = float(row["tp_pct"]) if row.get("tp_pct") is not None else None
            _sl = float(row["sl_pct"]) if row.get("sl_pct") is not None else None
            try:
                await router_execute(
                    chosen_mode=str(stale["chosen_mode"]),
                    user_id=user_id,
                    telegram_user_id=int(row["telegram_user_id"]),
                    role=str(row.get("role") or "user"),
                    market_id=stale["market_id"],
                    market_question=str(stale_market.get("question") or ""),
                    yes_token_id=stale_market.get("yes_token_id"),
                    no_token_id=stale_market.get("no_token_id"),
                    side=_stale_side,
                    size_usdc=_stale_size,
                    price=_stale_price,
                    idempotency_key=_stale_idem,
                    strategy_type=_STRATEGY_NAME,
                    tp_pct=_tp,
                    sl_pct=_sl,
                    trading_mode=str(row.get("trading_mode") or "paper"),
                )
                await _mark_executed(user_id, pub_uuid, _stale_idem)
                log.info(
                    "scan_outcome",
                    outcome="resumed",
                    mode=stale["chosen_mode"],
                    size=str(_stale_size),
                )
            except Exception as exc:
                err_str = f"{type(exc).__name__}: {exc}"
                log.error("scan_outcome", outcome="failed", error=err_str)
                try:
                    await _mark_failed(user_id, pub_uuid, _stale_idem, err_str)
                except Exception as mark_exc:
                    log.warning("exec_queue_mark_failed_error", error=str(mark_exc))
            return

    # 0a. Bankroll circuit breaker (WARP/R00T/bankroll-circuit-breaker,
    #     ref Polybot directive 1.4 + #6). Per-user latch checked BEFORE
    #     dedup / open-position / strategy gates so a tripped user does
    #     not consume any work for net new entries. The crash-recovery
    #     branch (step 0) runs FIRST so an already-approved-but-
    #     interrupted trade still completes — the breaker only blocks
    #     NEW entries, never the recovery of in-flight ones.
    #
    #     Reference: _bankroll_ema_baseline maintained by Lane 5
    #     (bankroll-dynamic-sizing). Trip at `baseline * THRESHOLD`,
    #     resume at `baseline * THRESHOLD * (1 + HYSTERESIS)`.
    #     Operator escape hatch: BANKROLL_CIRCUIT_BREAKER_ENABLED=false
    #     (default) disables the gate entirely.
    try:
        from ...config import get_settings as _gs_cb
        _cfg_cb = _gs_cb()
        _cb_enabled = bool(getattr(_cfg_cb, "BANKROLL_CIRCUIT_BREAKER_ENABLED", False))
    except Exception as exc:
        # AGENTS.md hard rule: zero silent failures. Log the diagnostic
        # context and fail closed — disable the gate rather than risk a
        # crashed config read silently locking every user out.
        log.warning(
            "bankroll_circuit_breaker_config_read_failed",
            error=str(exc),
            fallback_enabled=False,
        )
        _cb_enabled = False
    if _cb_enabled:
        try:
            _cb_threshold = float(_cfg_cb.BANKROLL_CIRCUIT_BREAKER_THRESHOLD)
            _cb_hysteresis = float(_cfg_cb.BANKROLL_CIRCUIT_BREAKER_HYSTERESIS)
        except Exception as exc:
            log.warning(
                "bankroll_circuit_breaker_params_read_failed",
                error=str(exc),
                fallback_threshold=0.20,
                fallback_hysteresis=0.10,
            )
            _cb_threshold = 0.20
            _cb_hysteresis = 0.10
        try:
            _cb_balance = float(row.get("balance_usdc") or 0.0)
        except (TypeError, ValueError):
            _cb_balance = 0.0
        # Decouple from Lane 5: warm the baseline ourselves so the
        # breaker works even when BANKROLL_DYNAMIC_SIZING_ENABLED=false.
        # No-op when a baseline already exists (Lane 5 path seeds it on
        # first multiplier call) so this never overwrites Lane 5 state.
        _ensure_bankroll_baseline_seeded(str(row["user_id"]), _cb_balance)
        _cb_tripped = _evaluate_bankroll_circuit_breaker(
            str(row["user_id"]),
            _cb_balance,
            threshold=_cb_threshold,
            hysteresis=_cb_hysteresis,
        )
        if _cb_tripped:
            # Mirror the helper's baseline source so the log payload
            # surfaces the exact denominator the gate used.
            _cb_baseline = _bankroll_ema_baseline.get(str(row["user_id"]))
            log.info(
                "scan_outcome",
                outcome="skipped_circuit_breaker",
                side=side,
                market_id=cand.market_id,
                strategy=cand.strategy_name,
                balance_usdc=_cb_balance,
                baseline_usdc=_cb_baseline,
                threshold=_cb_threshold,
                hysteresis=_cb_hysteresis,
                message=(
                    f"Bankroll circuit breaker tripped: balance "
                    f"{_cb_balance:.2f} below baseline "
                    f"{_cb_baseline if _cb_baseline is not None else 'N/A'} "
                    f"* threshold {_cb_threshold}; resume requires balance "
                    f"> baseline * threshold * (1 + {_cb_hysteresis})."
                ),
            )
            if telemetry is not None:
                telemetry.record_skip("skipped_circuit_breaker")
            return

    # 1. Permanent dedup — skip if execution_queue already has this row.
    if pub_uuid is not None:
        try:
            already = await _publication_already_queued(user_id, pub_uuid)
        except Exception as exc:
            log.warning("exec_queue_precheck_failed", error=str(exc))
            already = False
        if already:
            log.info("scan_outcome", outcome="skipped_dedup")
            if telemetry is not None:
                telemetry.record_skip("skipped_dedup")
            return

    # 1a-2. Safe-close inventory imbalance override
    #       (WARP/R00T/safe-close-imbalance-override, Polybot directive 1.2.1.c).
    #       Default OFF (dark launch). When ON it ONLY fires for
    #       late_entry_v3 candidates whose user has active_preset =
    #       'safe_close' AND has imbalanced existing exposure on the
    #       market. The override:
    #         - mutates cand.side to the lagging leg
    #         - stamps metadata["imbalance_override"] for audit
    #         - sets `_imbalance_override_active` so the open-position
    #           dedup below switches to the side-aware variant
    #       Other strategies / presets keep the broad open-position
    #       dedup unchanged.
    _imbalance_override_active = False
    _override_log: dict[str, Any] = {}
    try:
        from ...config import get_settings as _gs_imb
        _cfg_imb = _gs_imb()
        _imb_enabled = bool(getattr(_cfg_imb, "SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", False))
    except Exception as exc:
        # Fail CLOSED — disable the override path on config-read failure
        # so a broken config never silently lets us into the dedup-relax
        # branch. Matches the bankroll-circuit-breaker pattern.
        log.warning(
            "safe_close_imbalance_override_config_read_failed",
            error=str(exc),
            fallback_enabled=False,
        )
        _imb_enabled = False
    if (
        _imb_enabled
        and cand.strategy_name == "late_entry_v3"
        and (row.get("active_preset") or "").lower() == "safe_close"
    ):
        try:
            _threshold = float(_cfg_imb.SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC)
        except Exception as exc:
            log.warning(
                "safe_close_imbalance_threshold_read_failed",
                error=str(exc),
                fallback_usdc=5.0,
            )
            _threshold = 5.0
        _inventory = await _fetch_market_inventory_for_override(
            user_id, cand.market_id,
        )
        _imb = float(_inventory.imbalance_usdc) if _inventory is not None else 0.0
        if _inventory is not None and not _inventory.is_empty and abs(_imb) > _threshold:
            # Activate the side-aware dedup whenever a significant
            # imbalance exists — even if the candidate naturally
            # targets the lagging leg (no flip required). Otherwise
            # the broad market-wide dedup would block a correctly-
            # directed rebalance entry because the heavy-leg position
            # is already open. Gemini-flagged inconsistency.
            _imbalance_override_active = True
            # Lagging leg is the side with LESS exposure: imb > 0 means
            # YES-heavy → lagging is NO. imb < 0 → lagging is YES.
            # SignalCandidate.side validator enforces uppercase
            # ('YES' / 'NO'); the lowercase `side` local is the
            # execution-engine-facing convention. Track both.
            lagging_side_upper = "NO" if _imb > 0 else "YES"
            lagging_side_lower = lagging_side_upper.lower()
            current_side_lower = (cand.side or "").lower()
            if current_side_lower != lagging_side_lower:
                _override_log = {
                    "original_side": current_side_lower,
                    "new_side": lagging_side_lower,
                    "imbalance_usdc": round(_imb, 4),
                    "threshold_usdc": _threshold,
                    "yes_size_usdc": str(_inventory.yes_size_usdc),
                    "no_size_usdc": str(_inventory.no_size_usdc),
                }
                log.info(
                    "scan_outcome",
                    outcome="imbalance_override_applied",
                    market_id=cand.market_id,
                    strategy=cand.strategy_name,
                    **_override_log,
                    message=(
                        f"Safe-close imbalance override: "
                        f"{current_side_lower} → {lagging_side_lower} "
                        f"(imbalance ${_imb:.2f} > ${_threshold:.2f})"
                    ),
                )
                # SignalCandidate is a frozen dataclass with an
                # uppercase-side validator. `dataclasses.replace`
                # requires the uppercase form; the local `side`
                # variable stays lowercase for the rest of the function.
                _new_md = dict(cand.metadata)
                _new_md["imbalance_override"] = _override_log
                cand = _dc_replace(
                    cand, side=lagging_side_upper, metadata=_new_md,
                )
                side = lagging_side_lower
                # _imbalance_override_active was already set True above
                # when |imbalance| > threshold; the side-flip is a
                # subset of that condition.

    # 1b. Open-position market dedup — skip if user already holds an open
    #     position on this market_id. Closes the race window between concurrent
    #     ticks that both clear gate step 10 (orders-table dedup) before either
    #     has committed its position row. Crash-recovery resumes above this
    #     check so stale 'queued' rows are not blocked.
    #
    #     Override-aware: when the imbalance override above mutated
    #     cand.side, switch to the side-aware variant so we only block
    #     if the user already holds a position on the NEW (lagging)
    #     side. Otherwise the broad market-wide dedup would defeat the
    #     rebalance — the whole point of the override is to enter the
    #     opposite leg.
    try:
        if _imbalance_override_active:
            _is_dup = await _has_open_position_for_side(
                user_id, cand.market_id, side,
            )
        else:
            _is_dup = await _has_open_position_for_market(user_id, cand.market_id)
        if _is_dup:
            log.info("scan_outcome", outcome="skipped_open_position_exists",
                     market_id=cand.market_id,
                     side_aware=_imbalance_override_active,
                     message="duplicate skipped — open position exists for market")
            if telemetry is not None:
                telemetry.record_skip("skipped_open_position_exists")
            return
    except Exception as exc:
        log.warning("open_position_market_check_failed", error=str(exc))
        # On DB error fall through — gate step 10 remains the safety net.

    # 1c. Signal freshness gate — reject publication-backed signals older than
    #     _MAX_SIGNAL_AGE_SECONDS. signal_publications.expires_at allows 4h for
    #     feed UI history; the execution engine enforces a tighter window so it
    #     never fills at a 3-hour-old market price that has already moved past
    #     the TP target. Gate is skipped for lib-strategy candidates (pub_uuid
    #     is None) because those always carry signal_ts=now (see
    #     lib_strategy_runner.py) and must not be affected by user processing order.
    if pub_uuid is not None:
        _signal_age = (datetime.now(timezone.utc) - cand.signal_ts).total_seconds()
        if _signal_age > _MAX_SIGNAL_AGE_SECONDS:
            log.info(
                "scan_outcome",
                outcome="skipped_signal_stale",
                age_seconds=round(_signal_age),
                threshold=_MAX_SIGNAL_AGE_SECONDS,
                message=f"Signal too old ({round(_signal_age)}s > {_MAX_SIGNAL_AGE_SECONDS}s threshold)",
            )
            if telemetry is not None:
                telemetry.record_skip("skipped_signal_stale")
            return

    # 2. Market lookup.
    market = await _load_market(cand.market_id)
    if market is None:
        log.info("scan_outcome", outcome="skipped_market_not_synced")
        if telemetry is not None:
            telemetry.record_skip("skipped_market_not_synced")
        return

    # 2b. Target price drift guard — compare signal's target_price against
    #     current cached DB price for this side. If drift exceeds
    #     _MAX_TARGET_DRIFT_PCT the market has moved too far since the
    #     signal was published; executing would produce an unrealistic fill.
    #     Guard only applies to feed signals (pub_uuid is not None) because
    #     lib-strategy candidates always carry fresh prices (signal_ts=now).
    #     Uses same primary→fallback→0.5 resolution as _build_trade_signal so
    #     the guard evaluates the identical price the trade engine will use.
    if pub_uuid is not None:
        _target = float(cand.metadata.get("target_price") or 0.0)
        _price_primary = market.get(f"{side}_price")
        _price_fallback = market.get("no_price" if side == "yes" else "yes_price")
        _current = float(
            _price_primary if _price_primary is not None
            else (_price_fallback if _price_fallback is not None else 0.5)
        )
        if _target > 0:
            _drift = abs(_current - _target) / _target
            if _drift > _MAX_TARGET_DRIFT_PCT:
                log.info(
                    "scan_outcome",
                    outcome="skipped_price_drifted",
                    side=side,
                    target_price=_target,
                    current_price=_current,
                    drift_pct=round(_drift * 100, 1),
                    threshold_pct=round(_MAX_TARGET_DRIFT_PCT * 100, 1),
                    message=(
                        f"Price drifted {round(_drift * 100, 1)}% "
                        f"(target={_target:.4f} current={_current:.4f}) "
                        f"> {round(_MAX_TARGET_DRIFT_PCT * 100)}% threshold"
                    ),
                )
                if telemetry is not None:
                    telemetry.record_skip("skipped_price_drifted")
                return

    # 2c. Liquidity filter — skip markets below the user's configured threshold.
    min_liquidity = float(row.get("min_liquidity_threshold") or 0.0)
    if min_liquidity > 0:
        market_liquidity = float(market.get("liquidity_usdc") or 0.0)
        if market_liquidity < min_liquidity:
            log.info(
                "scan_outcome",
                outcome="skipped_liquidity",
                market_liquidity=market_liquidity,
                threshold=min_liquidity,
                message=f"Skipped: liquidity ${market_liquidity:.0f} below threshold ${min_liquidity:.0f}",
            )
            if telemetry is not None:
                telemetry.record_skip("skipped_liquidity")
            return

    # 3. Build TradeSignal — typed contract for TradeEngine (gate + paper fill).
    idem_key = _build_idempotency_key(user_id, cand.market_id, side, pub_uuid)

    # 3b. Resolve the live fill price. Two sources, in priority order:
    #
    #     (a) Candidate metadata `entry_price` — for late_entry_v3 candidates,
    #         this is the favored-side best ASK from CLOB /book at scan time
    #         (computed by `_evaluate_market._best_ask`). Already tick-aligned
    #         + interior because /book returns the real orderbook ladder.
    #         The scan→fill latency is sub-second, so the orderbook hasn't
    #         materially moved; using it eliminates the get_live_market_price
    #         round trip AND the Gamma `outcomePrices` seed/midpoint fallback
    #         that contaminated 200 flip_hunter positions on 2026-05-28.
    #
    #     (b) get_live_market_price fallback for candidates that DON'T carry
    #         metadata["entry_price"] (signal_following, momentum, etc., which
    #         enter on Gamma-aware longshot markets where sub-cent last-trade
    #         prices are legitimate — see WARP-38).
    _live_fill_price: float | None = None
    _meta_entry = cand.metadata.get("entry_price")
    if _meta_entry is not None:
        try:
            _candidate_entry = float(_meta_entry)
            if 0.0 < _candidate_entry < 1.0:
                _live_fill_price = _candidate_entry
        except (TypeError, ValueError):
            _live_fill_price = None

    # 3b-0. TOB freshness gate (WARP/R00T/tob-freshness-gate, ref Directive 7).
    #       Reject the candidate when the orderbook snapshot used to compute
    #       metadata["entry_price"] is older than TOB_STALE_MS. Scope: only
    #       candidates that carry metadata["entry_price_ts"] (late_entry_v3 —
    #       close_sweep / safe_close / flip_hunter); candidates without the
    #       stamp (signal_following / momentum / copy_trade) bypass cleanly.
    #       Disable by setting TOB_STALE_MS=0 in config / env.
    #
    #       Why: scan -> _process_candidate -> gate -> CLOB submission can take
    #       multiple seconds when scheduler back-pressures or the executor is
    #       busy; firing a trade on an orderbook snapshot that is several
    #       seconds old is the directional analogue of the sub-cent stale-
    #       Gamma bug (PR #1413) — the live mark has already moved by the time
    #       the order leaves the router, so the strategy's intended setup is
    #       no longer the setup we're actually buying.
    _meta_ts = cand.metadata.get("entry_price_ts")
    if _meta_ts is not None:
        try:
            from ...config import get_settings as _get_settings_tob
            _tob_stale_ms = int(_get_settings_tob().TOB_STALE_MS)
        except Exception as exc:
            # AGENTS.md hard rule: zero silent failures. Log the diagnostic
            # context, then fall back to the documented default so the gate
            # remains operative even on a config-read failure.
            log.warning(
                "tob_stale_ms_config_read_failed",
                error=str(exc),
                fallback_ms=2000,
            )
            _tob_stale_ms = 2000
        if _tob_stale_ms > 0:
            try:
                _tob_age_ms = (
                    datetime.now(timezone.utc).timestamp() - float(_meta_ts)
                ) * 1000.0
            except (TypeError, ValueError):
                _tob_age_ms = None
            if _tob_age_ms is not None and _tob_age_ms > _tob_stale_ms:
                log.info(
                    "scan_outcome",
                    outcome="skipped_stale_tob",
                    side=side,
                    market_id=cand.market_id,
                    strategy=cand.strategy_name,
                    age_ms=round(_tob_age_ms, 1),
                    threshold_ms=_tob_stale_ms,
                    message=(
                        f"Orderbook snapshot age {_tob_age_ms:.0f}ms exceeds "
                        f"TOB_STALE_MS={_tob_stale_ms}; rejecting to avoid "
                        f"firing on stale CLOB data."
                    ),
                )
                if telemetry is not None:
                    telemetry.record_skip("skipped_stale_tob")
                return

    # 3b-0a. Complete-set edge gate (WARP/R00T/complete-set-edge-gate, ref
    #        directive 1.1). Polymarket binary UP/DOWN settles to $1.00 at
    #        expiry → `cost = ask_UP + ask_DOWN` is the spot arb bound; the
    #        complementary `edge = 1 - cost` is the per-tick profit a taker
    #        could lock in by buying both legs. When edge < MIN_COMPLETE_SET_EDGE
    #        the market is too efficiently priced for the per-side entry to
    #        carry a real edge: the strategy's directional thesis is paying
    #        full price for a coin flip after fees, with no arb safety net.
    #
    #        The metric was stamped observationally by Lane 3
    #        (late_entry_v3._evaluate_market → metadata["complete_set_edge"]);
    #        this gate promotes it to a hard reject. Scoped to candidates that
    #        carry the stamp (late_entry_v3 — close_sweep / safe_close /
    #        flip_hunter); signal_following / momentum / copy_trade bypass.
    #
    #        Operator escape hatch: MIN_COMPLETE_SET_EDGE=0 disables the gate
    #        without redeploy (runtime branches on `> 0`).
    _meta_edge = cand.metadata.get("complete_set_edge")
    if _meta_edge is not None:
        try:
            from ...config import get_settings as _get_settings_edge
            _min_edge = float(_get_settings_edge().MIN_COMPLETE_SET_EDGE)
        except Exception as exc:
            # AGENTS.md hard rule: zero silent failures. Log the diagnostic
            # context, then fall back to the documented default so the gate
            # remains operative even on a config-read failure.
            log.warning(
                "min_complete_set_edge_config_read_failed",
                error=str(exc),
                fallback=0.005,
            )
            _min_edge = 0.005
        if _min_edge > 0:
            try:
                _candidate_edge = float(_meta_edge)
            except (TypeError, ValueError) as exc:
                # AGENTS.md hard rule: zero silent failures. A malformed
                # complete_set_edge stamp would bypass the gate silently —
                # log it loud so the operator can fix the producer
                # (late_entry_v3._evaluate_market) and we don't ship
                # negative-arb entries on a broken stamp.
                log.warning(
                    "complete_set_edge_parse_failed",
                    market_id=cand.market_id,
                    strategy=cand.strategy_name,
                    raw=repr(_meta_edge),
                    error=str(exc),
                    message=(
                        "Candidate carried a non-numeric complete_set_edge "
                        "stamp; bypassing the gate for this candidate but "
                        "the producer should be fixed."
                    ),
                )
                _candidate_edge = None
            if _candidate_edge is not None and _candidate_edge < _min_edge:
                log.info(
                    "scan_outcome",
                    outcome="skipped_negative_arb",
                    side=side,
                    market_id=cand.market_id,
                    strategy=cand.strategy_name,
                    complete_set_edge=round(_candidate_edge, 4),
                    threshold=_min_edge,
                    message=(
                        f"Complete-set edge {_candidate_edge:.4f} below "
                        f"MIN_COMPLETE_SET_EDGE={_min_edge}; rejecting "
                        f"to avoid directional entry into market priced at or "
                        f"above the $1.00 settlement bound."
                    ),
                )
                if telemetry is not None:
                    telemetry.record_skip("skipped_negative_arb")
                return

    if _live_fill_price is None:
        try:
            _live_fill_price = await get_live_market_price(cand.market_id, side)
        except Exception as exc:
            log.warning("live_price_fetch_failed", market_id=cand.market_id, error=str(exc))

    # 3b-i. Candle-market tick-alignment gate (flip-hunter-stale-price-fix).
    #       Polymarket 5m crypto candle markets (slug ``{coin}-updown-5m-...``)
    #       use a 0.01 (1¢) CLOB tick. A live price that is not on the tick
    #       (e.g. 0.505) for one of these markets comes from the Gamma
    #       ``outcomePrices`` seed/midpoint (the initial MM quote written
    #       before any real CLOB activity), not a real fill price.
    #
    #       Returning that as a tradable mark caused 80/86 flip_hunter
    #       positions over one session to enter at exactly 0.505 across
    #       BTC/ETH/SOL/XRP/DOGE/BNB simultaneously; combined with the
    #       synthetic TP fill (exit_watcher._tp_exit_price = entry*(1+tp%))
    #       every TP-hit landed at the identical 0.58075 across coins for
    #       indistinguishable +$0.50 paper P&L.
    #
    #       Scoped to candle markets only — thin longshot markets on other
    #       slugs DO legitimately surface sub-cent Gamma last-trade prices
    #       (e.g. 0.055 for a 5.5c longshot) and signal_following etc.
    #       must continue to trade them.
    if _live_fill_price is not None:
        _slug = str(market.get("slug") or "")
        _is_candle = "updown" in _slug
        if _is_candle:
            _cents = _live_fill_price * 100.0
            if abs(_cents - round(_cents)) > 1e-6:
                log.info(
                    "scan_outcome",
                    outcome="skipped_sub_cent_price",
                    side=side,
                    live_fill_price=_live_fill_price,
                    market_id=cand.market_id,
                    slug=_slug,
                    strategy=cand.strategy_name,
                    message=(
                        f"Candle market live price {_live_fill_price} not on "
                        f"0.01 tick — Gamma seed/midpoint fallback, not real "
                        f"CLOB activity"
                    ),
                )
                if telemetry is not None:
                    telemetry.record_skip("skipped_sub_cent_price")
                return

    # 3c. Fill-time price-band re-check. Candle markets (late_entry_v3) can drift
    #     0.10+ between scan and fill — without this gate, trades fired at prices
    #     unrelated to the preset's intended band (e.g. safe_close 5.5% of trades
    #     in [0.60, 0.70), 47% in coin-flip [0.45, 0.55] over 24h on prod).
    #     The candidate's metadata declares the band that was satisfied at scan
    #     time (fav_price_min/max); a live fill outside that band means the
    #     market moved past the strategy's intended setup and we must NOT fill.
    #     Safe for any strategy that omits the band metadata — gate no-ops.
    if (
        _live_fill_price is not None
        and cand.metadata.get("fav_price_min") is not None
        and cand.metadata.get("fav_price_max") is not None
    ):
        try:
            _f_min = float(cand.metadata["fav_price_min"])
            _f_max = float(cand.metadata["fav_price_max"])
        except (TypeError, ValueError):
            _f_min = _f_max = None  # type: ignore[assignment]
        if _f_min is not None and _f_max is not None and (
            _live_fill_price < _f_min or _live_fill_price >= _f_max
        ):
            log.info(
                "scan_outcome",
                outcome="skipped_fill_drifted",
                side=side,
                candidate_entry_price=cand.metadata.get("entry_price"),
                live_fill_price=_live_fill_price,
                fav_price_min=_f_min,
                fav_price_max=_f_max,
                strategy=cand.strategy_name,
                message=(
                    f"Fill price {_live_fill_price:.4f} drifted outside band "
                    f"[{_f_min:.2f}, {_f_max:.2f}) — candle moved between scan and fill"
                ),
            )
            if telemetry is not None:
                telemetry.record_skip("skipped_fill_drifted")
            return

    # 3d. Safe-close direction concentration gate
    #     (WARP/R00T/safe-close-direction-limit, Lane 4/5).
    #     Only fires when the user's active_preset == "safe_close".
    #     Other presets (close_sweep / flip_hunter / signal_following) bypass.
    #
    #     Rationale: late_entry_v3 chooses side dynamically per scan
    #     (`fav_side = "YES" if yes_ask > no_ask else "NO"`), so there is
    #     no per-candle bias. But in a trending market the same side
    #     ends up favoured candle after candle — the bot then aggregates
    #     directional risk that the per-candle filter never sees. This
    #     gate caps that aggregate at SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR
    #     per (user, side) within a rolling 1h window.
    #
    #     Set SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=0 to disable; runtime
    #     branches on `> 0`. Negative values rejected at config load.
    if (row.get("active_preset") or "").lower() == "safe_close":
        try:
            from ...config import get_settings as _gs_safe_close
            _safe_close_limit = int(_gs_safe_close().SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR)
        except Exception as exc:
            log.warning(
                "safe_close_direction_limit_config_read_failed",
                error=str(exc),
                fallback=8,
            )
            _safe_close_limit = 8
        if _safe_close_limit > 0:
            _now_ts = datetime.now(timezone.utc).timestamp()
            _recent = _safe_close_recent_count(str(user_id), side, _now_ts)
            if _recent >= _safe_close_limit:
                log.info(
                    "scan_outcome",
                    outcome="skipped_safe_close_direction_concentration",
                    side=side,
                    user_id=str(user_id),
                    market_id=cand.market_id,
                    recent_count=_recent,
                    limit=_safe_close_limit,
                    window_sec=_SAFE_CLOSE_DIRECTION_WINDOW_SEC,
                    message=(
                        f"User has {_recent} safe_close {side.upper()} "
                        f"entries in the last hour (limit "
                        f"{_safe_close_limit}); skipping to avoid "
                        f"directional concentration in trending markets."
                    ),
                )
                if telemetry is not None:
                    telemetry.record_skip("skipped_safe_close_direction_concentration")
                return

    try:
        signal = _build_trade_signal(
            row=row, cand=cand, market=market, idempotency_key=idem_key,
            live_price_override=_live_fill_price,
        )
    except Exception as exc:
        log.warning("trade_signal_build_failed", error=str(exc))
        return

    # 4. Execute through TradeEngine — risk gate (13 steps) is mandatory inside
    #    the engine; router_execute is never called directly on this path.
    try:
        result: TradeResult = await _engine.execute(signal)
    except Exception as exc:
        err_str = f"{type(exc).__name__}: {exc}"
        log.error("scan_outcome", outcome="failed", error=err_str)
        return

    if not result.approved:
        log.info(
            "scan_outcome",
            outcome="rejected",
            reason=result.rejection_reason,
            step=result.failed_gate_step,
        )
        if telemetry is not None:
            telemetry.record_rejection(result.failed_gate_step, result.rejection_reason or "unknown")
        return

    # 5. Record in execution_queue — post-execution audit + permanent dedup anchor.
    #    On conflict (concurrent tick filled first): skip; paper engine idempotency
    #    key ensures the second call returned mode="duplicate".
    final_size = result.final_size_usdc or signal.proposed_size_usdc
    if result.mode != "duplicate":
        try:
            inserted = await _insert_execution_queue(
                user_id=user_id,
                strategy_name=cand.strategy_name,
                market_id=cand.market_id,
                side=side,
                publication_id=pub_uuid,
                suggested_size_usdc=signal.proposed_size_usdc,
                final_size_usdc=final_size,
                idempotency_key=idem_key,
                chosen_mode=result.chosen_mode or "paper",
            )
        except Exception as exc:
            log.warning("exec_queue_insert_failed", error=str(exc))
            inserted = False
        if inserted:
            try:
                await _mark_executed(user_id, pub_uuid, idem_key)
            except Exception as exc:
                log.warning("exec_queue_mark_executed_failed", error=str(exc))
        logger.info(
            "paper_execution",
            market_id=cand.market_id,
            side=side,
            size=str(final_size),
            mode=result.chosen_mode,
            strategy=cand.strategy_name,
        )
        log.info(
            "scan_outcome",
            outcome="accepted",
            mode=result.chosen_mode,
            size=str(final_size),
        )
        if telemetry is not None:
            telemetry.record_approved()
        # Record this entry for the safe_close direction-concentration
        # limiter (Lane 4). Guard on `inserted` so a concurrent-tick
        # ON CONFLICT skip (another tick already won and recorded) does
        # not double-count toward the user's directional cap. Also
        # guard on result.mode != "duplicate" (implicit — we're already
        # inside that branch) so engine-level idempotency dedup also
        # bypasses the counter.
        if inserted and (row.get("active_preset") or "").lower() == "safe_close":
            _safe_close_record_entry(
                str(user_id), side, datetime.now(timezone.utc).timestamp(),
            )

        # Fast top-up (WARP/R00T/flip-hunter-fast-topup, directive 1.5
        # + 1.3.2). Fire-and-forget — failures inside the helper are
        # caught + logged, never propagated. Only attempts after a
        # genuinely-new fill (gated on `inserted`); a duplicate /
        # concurrent-tick skip doesn't trigger a top-up.
        if inserted:
            try:
                await _maybe_fire_fast_topup(
                    row=row,
                    market=market,
                    just_filled_side=side,
                    just_filled_size_usdc=Decimal(str(final_size)),
                    log=log,
                )
            except Exception as exc:
                log.warning("fast_topup_unexpected_error", error=str(exc))
    else:
        log.info("scan_outcome", outcome="duplicate", mode=result.chosen_mode)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _filter_markets_by_category(markets: list[dict], filters: list[str]) -> list[dict]:
    """Filter Gamma market dicts by category. Empty filters = all markets."""
    if not filters:
        return markets
    lower = {f.lower() for f in filters}
    result = []
    for m in markets:
        cat = (
            m.get("category")
            or m.get("groupItemTitle")
            or m.get("slug", "")
        ).lower()
        if any(f in cat for f in lower):
            result.append(m)
    return result


def _diversify_lib_candidates(
    candidates: list[SignalCandidate], user_id: Any
) -> list[SignalCandidate]:
    """Order lib-strategy candidates by sha1(user_id:market_id) so different
    users enter different markets when multiple candidates are available.

    Mirrors signal_evaluator._diversify_order — same deterministic key so a
    user does not churn positions between ticks, but different users see a
    different prefix of the eligible candidate set.
    """
    seed = str(user_id)

    def _key(c: SignalCandidate) -> str:
        return hashlib.sha1(f"{seed}:{c.market_id}".encode()).hexdigest()

    return sorted(candidates, key=_key)


async def _fetch_markets_for_lib_strategies() -> list[dict]:
    """Fetch active markets from Gamma /events, annotated with event-level tags.

    Uses get_events_with_markets() so each returned dict carries a ``category``
    field built from the parent event's tag labels (e.g. ``"crypto finance"``).
    _filter_markets_by_category() can then correctly match dashboard categories
    (Politics/Sports/Crypto/Finance/…) instead of substring-matching the raw
    event slug that Gamma /markets returns in ``groupItemTitle`` / ``slug``.

    Returns empty list on failure — lib strategies handle empty input gracefully.
    """
    try:
        return await _polymarket.get_events_with_markets(limit=200)
    except Exception as exc:
        logger.warning("lib_strategy_market_fetch_failed", error=str(exc))
        return []


async def run_once() -> None:
    """Run one tick of the lib-strategy scan loop for all enrolled users.

    Per-user execution:
      Markets are fetched once from Gamma API then filtered per-user by
      category_filters before being passed to each lib strategy. strategy_params
      from user_settings are forwarded as config so strategies apply user-specific
      thresholds (drop_threshold, min_liquidity, etc.).

    Each user is processed independently — an exception for one user does
    not prevent other users from being scanned on the same tick.
    """
    from ...config import get_settings as _get_settings
    from ...domain.strategy.registry import StrategyRegistry as _Registry

    try:
        _s = _get_settings()
        _live_trading: bool = bool(
            _s.ENABLE_LIVE_TRADING
            and _s.EXECUTION_PATH_VALIDATED
            and _s.CAPITAL_MODE_CONFIRMED
        )
    except Exception:
        _live_trading = False
    _mode: str = "LIVE" if _live_trading else "PAPER"

    # Refresh the operator on/off switch once per tick (fail-safe).
    await _refresh_disabled_strategies()

    # Count all strategies known to the process (lib + domain registry).
    _lib_count = len(ENABLED_STRATEGIES) + len(DEFERRED_STRATEGIES)
    _domain_count = len(_Registry.instance().list_available())
    _strategies_loaded = _lib_count + _domain_count

    tel = ScanTelemetry()
    run_id: str = str(_uuid_mod.uuid4())

    await _insert_scan_run(
        run_id,
        strategies_loaded=_strategies_loaded,
        live_trading=_live_trading,
        mode=_mode,
    )

    logger.info("signal_scan_job_started", scan_run_id=run_id, strategies_loaded=_strategies_loaded)

    try:
        users = await _load_enrolled_users()
    except Exception as exc:
        logger.error("signal_scan_load_users_failed", error=str(exc))
        await _finish_scan_run(run_id, tel)
        return

    await _event_bus.emit("pipeline.strategy_scan_started", user_count=len(users))

    if not users:
        await _finish_scan_run(run_id, tel)
        return

    markets = await _fetch_markets_for_lib_strategies()

    tel.users_evaluated = len(users)
    tel.markets_seen = len(markets)

    try:
        late_entry_strat = StrategyRegistry.instance().get(_LATE_ENTRY_V3_NAME)
    except KeyError:
        late_entry_strat = None
        logger.debug("late_entry_v3_not_registered")

    candidates_processed = 0
    candidates_errored = 0
    late_entry_signals = 0

    for row in users:
        active_preset = row.get("active_preset")
        # Safety guard: skip users who have not yet configured a strategy preset.
        # Without this, _preset_allows(None, lib_name) falls back to _LIB_STRATEGY_NAMES
        # and fires signal_following for every unconfigured user.
        if active_preset is None:
            logger.warning(
                "scan_skipped_no_preset",
                user_id=str(row["user_id"]),
                reason="active_preset is NULL — user must configure a strategy before trading",
            )
            continue
        category_filters: list[str] = list(row.get("category_filters") or [])
        strategy_params: dict = _coerce_jsonb(row.get("strategy_params"), {})
        _tf = row.get("selected_timeframe")
        selected_timeframe: str | None = str(_tf) if _tf else None
        selected_assets: list[str] = _filter_monitor_only_assets(row.get("selected_assets"))
        user_log = logger.bind(user_id=str(row["user_id"]), preset=active_preset)

        # Filter market list to user's chosen categories (empty = all markets).
        user_markets = _filter_markets_by_category(markets, category_filters)

        # Candle presets target the currently-live candle window directly
        # (by deterministic slug), so they see the in-window markets with real
        # liquidity instead of the far-future batch a broad list fetch returns.
        crypto_window_markets: list[dict] = []
        if active_preset in _CANDLE_PRESETS:
            try:
                crypto_window_markets = await _polymarket.get_crypto_window_markets(
                    selected_timeframe or "5m", selected_assets or None
                )
                # Upsert into the markets table so _process_candidate's
                # _load_market gate resolves them (market_sync never pulls these
                # micro candle markets) and the trade engine gets their tokens.
                await _upsert_crypto_window_markets(crypto_window_markets)
            except Exception as exc:
                user_log.warning("crypto_window_fetch_failed", error=str(exc))
                crypto_window_markets = []

        # Run domain late_entry_v3 strategy when the active preset
        # permits (close_sweep + full_auto/default). Like confluence_scalper it
        # applies its crypto-candle eligibility + entry-window gates inside
        # scan(), so emitted candidates already satisfy the asset whitelist and
        # the final-seconds timing window. The crypto-window upsert above runs
        # for close_sweep, so these candidates resolve in _load_market.
        if late_entry_strat is not None and _preset_allows(
            active_preset, _LATE_ENTRY_V3_NAME
        ):
            try:
                user_ctx = _build_user_context(row)
                market_filters = _build_market_filters(user_ctx.risk_profile, row)
                # Pass preset-specific params when the user is on a candle preset;
                # full_auto/default passes None so scan() falls back to global config.
                # Uses live config (env-tunable) + timeframe-aware flip_hunter via
                # _resolve_preset_params — same resolver as run_close_sweep_fast.
                _le_pp = (
                    _resolve_preset_params(active_preset, row.get("selected_timeframe"))
                    if active_preset in _CANDLE_PRESETS else None
                )
                _le_force = _le_pp.get("force_exit_at_rem_sec") if _le_pp else None
                late_entry_cands = await late_entry_strat.scan(
                    market_filters, user_ctx,
                    min_ask_diff=float(_le_pp["min_ask_diff"]) if _le_pp else None,
                    entry_window_sec=float(_le_pp["entry_window_sec"]) if _le_pp else None,
                    fav_price_min=float(_le_pp["fav_price_min"]) if _le_pp else None,
                    fav_price_max=float(_le_pp["fav_price_max"]) if _le_pp else None,
                    min_entry_sec=float(_le_pp["min_entry_sec"]) if _le_pp and "min_entry_sec" in _le_pp else None,
                    underdog_mode=bool(_le_pp.get("underdog_mode", False)) if _le_pp else False,
                    force_exit_at_rem_sec=float(_le_force) if _le_force is not None else None,
                    max_leg_spread=(
                        float(_le_pp["max_leg_spread"])
                        if _le_pp and "max_leg_spread" in _le_pp
                        else None
                    ),
                )
            except Exception as exc:
                user_log.warning("late_entry_v3_run_failed", error=str(exc))
                late_entry_cands = []

            late_entry_signals += len(late_entry_cands)
            user_log.info(
                "strategy_run",
                strategy=_LATE_ENTRY_V3_NAME,
                candidates_emitted=len(late_entry_cands),
                zero_reason="filter_or_no_match" if not late_entry_cands else None,
            )
            if not late_entry_cands:
                tel.record_zero_reason(_LATE_ENTRY_V3_NAME, "filter_or_no_match")
            tel.candidates_emitted += len(late_entry_cands)
            for cand in _diversify_lib_candidates(late_entry_cands, row["user_id"]):
                try:
                    await _process_candidate(row, cand, tel)
                    candidates_processed += 1
                except Exception as exc:
                    candidates_errored += 1
                    user_log.error(
                        "signal_scan_candidate_unhandled",
                        market_id=cand.market_id,
                        strategy=_LATE_ENTRY_V3_NAME,
                        error=str(exc),
                    )

        # Phase C: evaluate signal_publications feed for this user.
        # Uses signal_evaluator which reads user's subscribed feeds and
        # returns SignalCandidates with metadata["publication_id"] set.
        # _process_candidate handles dedup via (user_id, publication_id) unique key.
        #
        # _preset_allows enforces BOTH the operator's global on/off toggle AND
        # the user's preset → strategy mapping. After WARP/R00T cleanup the only
        # visible presets are candle presets (close_sweep/safe_close/flip_hunter)
        # which route exclusively to late_entry_v3 — so this short-circuits for
        # every candle-preset user even when signal_following is globally ON.
        # That stops Phase C from silently producing signal-feed trades a user
        # picking a candle preset never asked for. Telemetry distinguishes the
        # two reasons so operators can see at a glance whether the gate fired
        # because of the global toggle or the preset restriction.
        feed_candidates: list[SignalCandidate] = []
        if not _preset_allows(active_preset, _STRATEGY_NAME):
            tel.record_zero_reason(
                "signal_feed",
                "globally_disabled"
                if _STRATEGY_NAME in _GLOBALLY_DISABLED_STRATEGIES
                else "preset_blocks_signal_following",
            )
        else:
            try:
                user_ctx = _build_user_context(row)
                market_filters = _build_market_filters(user_ctx.risk_profile, row)
                feed_candidates = await evaluate_publications_for_user(
                    user_context=user_ctx,
                    market_filters=market_filters,
                    strategy_name=_STRATEGY_NAME,
                )
            except Exception as exc:
                user_log.warning("signal_feed_eval_failed", error=str(exc))
                feed_candidates = []

        if not feed_candidates:
            tel.record_zero_reason("signal_feed", "no_publications_eligible")
        tel.candidates_emitted += len(feed_candidates)
        for cand in feed_candidates:
            try:
                await _process_candidate(row, cand, tel)
                candidates_processed += 1
            except Exception as exc:
                candidates_errored += 1
                user_log.error(
                    "signal_scan_feed_candidate_unhandled",
                    market_id=cand.market_id,
                    error=str(exc),
                )

    logger.info(
        "scan_input",
        scan_run_id=run_id,
        users_evaluated=tel.users_evaluated,
        markets_seen=tel.markets_seen,
        strategies_loaded=_strategies_loaded,
    )
    logger.info(
        "lib_strategy_scan_done",
        scan_run_id=run_id,
        strategies=1,  # late_entry_v3
        late_entry_signals=late_entry_signals,
        candidates_emitted=tel.candidates_emitted,
        risk_approved=tel.risk_approved,
        risk_rejected=tel.risk_rejected,
        paper_orders_created=tel.paper_orders_created,
        skip_breakdown=tel.skip_breakdown,
        zero_reason_breakdown=tel.zero_reason_breakdown,
        rejection_breakdown=tel.rejection_breakdown,
    )
    await _finish_scan_run(run_id, tel)
    await _event_bus.emit(
        "pipeline.strategy_scan_done",
        strategy_count=1,
        total_signals=late_entry_signals,
    )
    await _event_bus.emit(
        "pipeline.scan_completed",
        user_count=len(users),
        candidates_processed=candidates_processed,
        candidates_errored=candidates_errored,
    )


_CANDLE_PRESETS: frozenset[str] = frozenset({"close_sweep", "safe_close", "flip_hunter"})

# Per-preset scan params for late_entry_v3. Kreo-aligned (post WARP/ROOT/safe-close-flip-hunter-kreo-parity).
# close_sweep : final 35s, moderate lean, fav ≥0.55 — holds to candle resolution
# safe_close  : enter rem 30–60s (elapsed 240–270s 5m / 840–870s 15m), Min Edge 1%, force-exit rem 30s
# flip_hunter : Kreo "Early Flip Hunter" — enter FIRST 140s 5m / 420s 15m, With Trend (favored side),
#               Min Edge 3%, force-exit at upper bound of entry window
# Static fallback when get_settings() fails (import / test edge cases).
# Runtime path always goes through _resolve_preset_params for live env override.
_CANDLE_PRESET_STATIC: dict[str, dict[str, object]] = {
    "close_sweep": {
        "min_ask_diff":    0.05,
        "entry_window_sec": 35.0,
        "fav_price_min":   0.55,
        "fav_price_max":   0.70,
    },
    "safe_close": {
        "min_ask_diff":    0.01,                # Kreo Min Edge 1%
        "entry_window_sec": 60.0,
        "fav_price_min":   0.60,
        "fav_price_max":   0.70,
        "min_entry_sec":   30.0,
        "force_exit_at_rem_sec": 30.0,          # exit BEFORE noisy final 30s
    },
    "flip_hunter": {
        "min_ask_diff":    0.03,                # Kreo Min Edge 3%
        "entry_window_sec": 300.0,              # 5m default — _resolve overrides per tf
        "fav_price_min":   0.50,                # favored side (was 0.26 underdog floor)
        "fav_price_max":   0.95,                # skip near-resolved (was 0.36 underdog ceiling)
        "min_entry_sec":   160.0,               # 5m default — _resolve overrides per tf
        "underdog_mode":   False,               # Kreo "With Trend" → favored side
        "force_exit_at_rem_sec": 160.0,         # 5m default — _resolve overrides per tf
    },
}
# Back-compat alias kept so any external test imports still resolve.
_CANDLE_PRESET_PARAMS: dict[str, dict[str, object]] = _CANDLE_PRESET_STATIC


def _random_close_sweep_min_edge(cfg) -> float:
    """Per-scan randomized close_sweep min_ask_diff in [MIN, MAX] (Kreo ~2%).

    Returns the lower bound when MIN >= MAX (pinned/deterministic) so tests can
    fix the value via config. Never raises — falls back to the fixed default.
    """
    try:
        lo = float(cfg.PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MIN)
        hi = float(cfg.PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MAX)
    except Exception:
        return 0.02
    if lo >= hi:
        return lo
    return round(random.uniform(lo, hi), 4)


def _resolve_preset_params(
    active_preset: str | None,
    timeframe: str | None,
) -> dict[str, object]:
    """Return the late_entry_v3 scan params for (preset, timeframe).

    Reads live config so Fly secrets can override per-preset values without a
    code change. Falls back to ``_CANDLE_PRESET_STATIC`` on any config error.

    flip_hunter is the only timeframe-aware preset (Kreo splits elapsed-time
    windows per candle length: 0–140s for 5m, 0–420s for 15m). safe_close +
    close_sweep use rem-time semantics that are identical across timeframes.
    """
    if active_preset not in _CANDLE_PRESETS:
        return _CANDLE_PRESET_STATIC.get(
            active_preset or "close_sweep", _CANDLE_PRESET_STATIC["close_sweep"]
        )
    tf = (timeframe or "5m").lower()
    try:
        from ...config import get_settings as _gs
        cfg = _gs()
    except Exception:
        # Static fallback — flip_hunter needs a 15m variant since its rem window
        # scales with candle length. safe_close + close_sweep are tf-invariant.
        if active_preset == "flip_hunter" and tf == "15m":
            base = dict(_CANDLE_PRESET_STATIC["flip_hunter"])
            base["entry_window_sec"] = 900.0
            base["min_entry_sec"] = 480.0
            base["force_exit_at_rem_sec"] = 480.0
            return base
        return _CANDLE_PRESET_STATIC[active_preset]
    if active_preset == "close_sweep":
        return {
            # Kreo "Min Edge" ~2%: randomize the entry lean threshold per scan
            # in [MIN, MAX] (2–4%) so entries are not pinned to one fixed value.
            "min_ask_diff":    _random_close_sweep_min_edge(cfg),
            "entry_window_sec": cfg.PRESET_CLOSE_SWEEP_WINDOW_SEC,
            "fav_price_min":   cfg.PRESET_CLOSE_SWEEP_FAV_PRICE_MIN,
            "fav_price_max":   0.70,
            # WARP/R00T/close-sweep-spread-gate: per-leg bid-ask spread guard
            # scoped to close_sweep (final-candle illiquidity → high slippage).
            # safe_close + flip_hunter omit this key → max_leg_spread=None → no-op.
            # `getattr` defensive so partial-mock cfg objects in tests don't break.
            "max_leg_spread":  getattr(cfg, "CLOSE_SWEEP_MAX_LEG_SPREAD", 0.02),
            # close_sweep force-exit (~8s before resolution) is applied on the
            # EXIT path via force_exit_at_rem_sec_for, not seeded here.
        }
    if active_preset == "safe_close":
        return {
            "min_ask_diff":    cfg.PRESET_SAFE_CLOSE_MIN_ASK_DIFF,
            "entry_window_sec": cfg.PRESET_SAFE_CLOSE_WINDOW_SEC,
            "fav_price_min":   cfg.PRESET_SAFE_CLOSE_FAV_PRICE_MIN,
            "fav_price_max":   0.70,
            "min_entry_sec":   cfg.PRESET_SAFE_CLOSE_MIN_ENTRY_SEC,
            "force_exit_at_rem_sec": cfg.PRESET_SAFE_CLOSE_FORCE_EXIT_REM_SEC,
        }
    # flip_hunter — Kreo Early Flip Hunter, timeframe-aware
    if tf == "15m":
        min_rem = cfg.PRESET_FLIP_HUNTER_15M_MIN_REM_SEC
        max_rem = cfg.PRESET_FLIP_HUNTER_15M_MAX_REM_SEC
        force_exit = cfg.PRESET_FLIP_HUNTER_15M_FORCE_EXIT_REM_SEC
    else:
        min_rem = cfg.PRESET_FLIP_HUNTER_5M_MIN_REM_SEC
        max_rem = cfg.PRESET_FLIP_HUNTER_5M_MAX_REM_SEC
        force_exit = cfg.PRESET_FLIP_HUNTER_5M_FORCE_EXIT_REM_SEC
    return {
        "min_ask_diff":    cfg.PRESET_FLIP_HUNTER_MIN_ASK_DIFF,
        "entry_window_sec": max_rem,
        "fav_price_min":   cfg.PRESET_FLIP_HUNTER_FAV_PRICE_MIN,
        "fav_price_max":   cfg.PRESET_FLIP_HUNTER_FAV_PRICE_MAX,
        "min_entry_sec":   min_rem,
        "underdog_mode":   False,           # Kreo With Trend
        "force_exit_at_rem_sec": force_exit,
    }


async def run_close_sweep_fast() -> None:
    """High-frequency scan for all candle-preset users (close_sweep, safe_close, flip_hunter).

    Late Entry V3 only enters in a specific window before candle close. The main
    run_once loop fires every SIGNAL_SCAN_INTERVAL (180s) and would step over
    that window, so this lighter loop runs every CLOSE_SWEEP_SCAN_INTERVAL
    (~15s) and scans ONLY candle-preset users with ONLY the late_entry_v3 domain
    strategy. It does not write a scan_runs row (telemetry is in-memory) to
    avoid flooding the table at this cadence; _process_candidate's idempotency
    + open-position dedup make the overlap with run_once's Phase-B2 harmless.

    Each user is isolated — one user's failure never blocks the rest.
    """
    from ...domain.strategy.registry import StrategyRegistry as _Registry

    try:
        late_entry_strat = _Registry.instance().get(_LATE_ENTRY_V3_NAME)
    except KeyError:
        logger.debug("close_sweep_fast: late_entry_v3 not registered")
        return

    # Honour the operator's global on/off switch in THIS loop too — run_once
    # gates via _preset_allows, but the fast candle loop has its own dispatch
    # and would otherwise keep trading a globally-disabled strategy. All candle
    # presets (close_sweep/safe_close/flip_hunter) route to late_entry_v3, so a
    # global disable of late_entry_v3 stops every candle entry here. Fail-safe:
    # a DB blip keeps the previous set (see _refresh_disabled_strategies).
    await _refresh_disabled_strategies()
    if _LATE_ENTRY_V3_NAME in _GLOBALLY_DISABLED_STRATEGIES:
        logger.info("close_sweep_fast: late_entry_v3 globally disabled — skipping tick")
        return

    try:
        users = await _load_enrolled_users()
    except Exception as exc:
        logger.error("close_sweep_fast_load_users_failed", error=str(exc))
        return

    tel = ScanTelemetry()
    fast_run_id: str = str(_uuid_mod.uuid4())
    candle_users_evaluated = 0
    _candle_markets_seen: int = 0  # max candle markets available across users in this tick
    for row in users:
        active_preset = row.get("active_preset")
        if active_preset not in _CANDLE_PRESETS:
            continue
        candle_users_evaluated += 1

        _tf = row.get("selected_timeframe")
        selected_timeframe: str | None = str(_tf) if _tf else None
        selected_assets: list[str] = _filter_monitor_only_assets(row.get("selected_assets"))
        user_log = logger.bind(user_id=str(row["user_id"]), preset=active_preset)

        # Per-user param resolution — flip_hunter is timeframe-aware so we cannot
        # share a single dict across users (mixed 5m/15m settings would clobber).
        pp = _resolve_preset_params(active_preset, selected_timeframe)

        # Upsert the live candle window so _process_candidate's _load_market
        # gate resolves the markets (market_sync never pulls these micro candles).
        try:
            crypto_window_markets = await _polymarket.get_crypto_window_markets(
                selected_timeframe or "5m", selected_assets or None
            )
            await _upsert_crypto_window_markets(crypto_window_markets)
            _candle_markets_seen = max(_candle_markets_seen, len(crypto_window_markets))
        except Exception as exc:
            user_log.warning("close_sweep_fast_window_fetch_failed", error=str(exc))

        try:
            user_ctx = _build_user_context(row)
            market_filters = _build_market_filters(user_ctx.risk_profile, row)
            _force_exit = pp.get("force_exit_at_rem_sec")
            cands = await late_entry_strat.scan(
                market_filters,
                user_ctx,
                min_ask_diff=float(pp["min_ask_diff"]),
                entry_window_sec=float(pp["entry_window_sec"]),
                fav_price_min=float(pp["fav_price_min"]),
                fav_price_max=float(pp["fav_price_max"]),
                min_entry_sec=float(pp["min_entry_sec"]) if "min_entry_sec" in pp else None,
                underdog_mode=bool(pp.get("underdog_mode", False)),
                force_exit_at_rem_sec=float(_force_exit) if _force_exit is not None else None,
                max_leg_spread=float(pp["max_leg_spread"]) if "max_leg_spread" in pp else None,
            )
        except Exception as exc:
            user_log.warning("close_sweep_fast_run_failed", error=str(exc))
            cands = []

        if not cands:
            user_log.info(
                "close_sweep_fast_tick",
                candidates=0,
                preset=active_preset,
                note="scan ran but no candidates passed gates — check late_entry_v3 scan_summary logs",
            )

        for cand in _diversify_lib_candidates(cands, row["user_id"]):
            try:
                await _process_candidate(row, cand, tel)
            except Exception as exc:
                user_log.error(
                    "close_sweep_fast_candidate_unhandled",
                    market_id=cand.market_id,
                    error=str(exc),
                )

    # Persist a scan_runs row only when this tick actually created paper orders.
    # Skipping zero-order ticks keeps the table clean at 15s cadence.
    if tel.paper_orders_created > 0:
        tel.users_evaluated = candle_users_evaluated
        tel.markets_seen = _candle_markets_seen
        from ...config import get_settings as _get_settings
        _cfg_live = _get_settings()
        _is_live = _cfg_live.ENABLE_LIVE_TRADING and _cfg_live.EXECUTION_PATH_VALIDATED and _cfg_live.CAPITAL_MODE_CONFIRMED
        await _insert_scan_run(
            fast_run_id,
            strategies_loaded=1,
            live_trading=_is_live,
            mode="LIVE" if _is_live else "PAPER",
        )
        await _finish_scan_run(fast_run_id, tel)


__all__ = [
    "run_once",
    "run_close_sweep_fast",
    "_filter_markets_by_category",
    "_diversify_lib_candidates",
]
