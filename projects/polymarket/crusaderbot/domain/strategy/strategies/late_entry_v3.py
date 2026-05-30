"""LateEntryV3Strategy — final-seconds momentum entry on crypto candle markets.

The edge (ref: github.com/bayuewalker/polybot_4coin src/strategy.py): on a short
crypto up/down candle market (BTC/ETH/SOL/BNB, 5m/15m), in the final seconds before
the window closes, buy the side the live CLOB already prices as the likely winner
(higher ask), and bail if the price flips against us.

Foundation contract:
    BaseStrategy.scan          — emit a YES/NO candidate for the favored side when
                                 the entry window, ask-difference, spread, and
                                 favored-price gates all pass.
    BaseStrategy.evaluate_exit — flip-stop: close once the favored side's live price
                                 falls to FLIP_STOP_PRICE or below.
    BaseStrategy.default_tp_sl — TP 15% / SL 8% (matches the close_sweep preset).

Pipeline boundary:
    DATA -> [STRATEGY <-- this file] -> INTELLIGENCE -> RISK -> EXECUTION

This module never places orders, never touches the risk gate, never bypasses
activation guards. Sizing is intentionally a *suggestion* (a small fraction of the
user's allocated capital) — the risk gate applies fractional Kelly and the position
caps to produce the final size. No fixed contract counts.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog

from ....config import get_settings
from ....integrations import polymarket as pm
from ..base import BaseStrategy
from ..eligibility import is_short_crypto_market
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

log = structlog.get_logger(__name__)

# Entry gates (mirror of the reference strategy).
# Final ~35s before close (ref Kreo Close Sweep: 5m Time 265-299s / 15m 865-899s).
# This narrow window only fires reliably under the dedicated high-frequency
# close_sweep scan loop (signal_scan_job.run_close_sweep_fast); the 180s main
# scan would step over it.
ENTRY_WINDOW_SEC: float = 35.0    # enter only in the final 35s of the candle
# Minimum best-ask lean between the two sides. BTC/ETH 5m/15m candles sit near
# 0.50/0.50, so a 0.30 lean basically never occurs and the strategy never
# traded; 0.05 captures a real late lean (~5c, ≈ the reference "min edge")
# while still skipping pure coin-flips. Key tunable — raise for stricter entries.
MIN_ASK_DIFF: float = 0.05
MAX_SPREAD: float = 1.05          # combined YES+NO asks must not be too wide
FAV_PRICE_MAX: float = 0.70       # skip expensive favored entries; fav>0.70 is a net-loss zone (low win-rate + asymmetric ~100% downside). Module fallback; env-tunable via LATE_ENTRY_FAV_PRICE_MAX.
FLIP_STOP_PRICE: float = 0.48     # exit when favored side's live price <= this

DEFAULT_TP_PCT: float = 0.15
DEFAULT_SL_PCT: float = 0.08

# Window step seconds by timeframe — used to derive the candle close from the
# slug ({coin}-updown-{tf}-{slot}) when the market dict carries no end date.
_TF_STEP_SECONDS: dict[str, int] = {"5m": 300, "15m": 900}

# Suggested-size envelope (the gate re-sizes downward via Kelly + caps).
_SUGGESTED_SIZE_FRACTION: float = 0.04
_SUGGESTED_SIZE_MIN_USDC: float = 1.0
_SUGGESTED_SIZE_MAX_USDC: float = 25.0       # 'auto' mode default ceiling
# Hard ceilings for the user-configurable per-trade cap. A user may raise the
# 'auto' $25 ceiling but NEVER beyond these absolute system limits; the risk
# gate's fractional Kelly + 10%-of-equity position fence still apply on top.
_ABS_MAX_PER_TRADE_USDC: float = 500.0
_MIN_PER_TRADE_PCT: float = 0.005            # 0.5% of equity
_MAX_PER_TRADE_PCT: float = 0.10             # 10% of equity


def resolve_per_trade_ceiling(
    equity_usdc: float,
    mode: str | None,
    max_usdc: float | None,
    max_pct: float | None,
) -> float:
    """Per-trade $ ceiling for the user's chosen mode, bounded by system limits.

    'fixed' -> max_usdc clamped to [$1, $500]. 'pct' -> equity x max_pct with
    max_pct clamped to [0.5%, 10%]. Anything else ('auto'/None/missing value)
    falls back to the system default ($25). Never returns more than the absolute
    per-trade cap.
    """
    if mode == "fixed" and max_usdc is not None and max_usdc > 0:
        return max(_SUGGESTED_SIZE_MIN_USDC, min(float(max_usdc), _ABS_MAX_PER_TRADE_USDC))
    if mode == "pct" and max_pct is not None and max_pct > 0:
        pct = min(max(float(max_pct), _MIN_PER_TRADE_PCT), _MAX_PER_TRADE_PCT)
        return max(
            _SUGGESTED_SIZE_MIN_USDC,
            min(max(0.0, equity_usdc) * pct, _ABS_MAX_PER_TRADE_USDC),
        )
    return _SUGGESTED_SIZE_MAX_USDC


def suggested_trade_size(
    base_usdc: float,
    capital_allocation_pct: float,
    *,
    ceiling_usdc: float | None = None,
) -> float:
    """Per-trade size = (equity x capital_allocation_pct) x fraction, clamped.

    ``base_usdc`` is the account equity (free balance + open-position value).
    The capital_allocation_pct (risk-profile CAP%) defines the deployable pool;
    a single trade takes only a small fraction of that pool, hard-capped at
    ``ceiling_usdc`` (default $25). So CAP% is NOT the per-trade size — e.g.
    equity $1000 x 60% x 4% = $24, capped $25. ``ceiling_usdc`` is the user's
    resolved max-per-trade (see resolve_per_trade_ceiling). The risk gate then
    re-sizes downward via fractional Kelly and the max-position fence. Shared
    with the WebTrader autotrade endpoint so the UI shows the engine's number.
    """
    cap = _SUGGESTED_SIZE_MAX_USDC if ceiling_usdc is None else max(0.0, ceiling_usdc)
    allocated = max(0.0, base_usdc) * max(0.0, capital_allocation_pct)
    return max(
        _SUGGESTED_SIZE_MIN_USDC,
        min(allocated * _SUGGESTED_SIZE_FRACTION, cap),
    )


class LateEntryV3Strategy(BaseStrategy):
    """Final-seconds momentum entry powering the Close Sweep preset.

    Compatible with every risk profile — close_sweep resolves to balanced, but
    the strategy itself imposes no profile-specific behaviour.
    """

    name = "late_entry_v3"
    version = "1.0.0"
    risk_profile_compatibility = ["conservative", "balanced", "aggressive", "custom"]

    def default_tp_sl(self) -> tuple[float, float]:
        return (DEFAULT_TP_PCT, DEFAULT_SL_PCT)

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
        *,
        min_ask_diff: float | None = None,
        entry_window_sec: float | None = None,
        fav_price_min: float | None = None,
        fav_price_max: float | None = None,
        min_entry_sec: float | None = None,
        underdog_mode: bool = False,
        force_exit_at_rem_sec: float | None = None,
        max_leg_spread: float | None = None,
    ) -> list[SignalCandidate]:
        """Emit one candidate per in-window crypto candle market.

        Callers (e.g. run_close_sweep_fast) may pass preset-specific overrides.
        When not provided, values fall back to global config / module defaults.

        ``min_entry_sec``: if set, skip markets with fewer seconds_left than
        this floor (safe_close: 30s — don't enter in the final 30s).

        ``underdog_mode``: when True, enter the cheap (low-probability) side
        priced within [fav_price_min, fav_price_max] instead of the majority
        side. Used by flip_hunter to catch asymmetric upside on late flips.

        ``force_exit_at_rem_sec``: if set, recorded in candidate metadata so the
        exit watcher closes the position when the candle's remaining time drops
        to this value (Kreo-style fixed-time exit; e.g. safe_close 30s exits
        BEFORE the noisy final 30s). When None, no time-based exit is applied
        and the position runs to TP/SL/flip-stop/market_expired as before.

        ``max_leg_spread``: if set (and > 0), reject any market where either
        leg's per-side bid-ask spread (``best_ask - best_bid``) exceeds the
        threshold. Scoped to ``close_sweep`` (the only preset that fires in
        the noisy final 35s where illiquidity → slippage); ``None`` no-ops
        for safe_close + flip_hunter which already entry earlier in the window.

        Returns an empty list on any failure or when no market qualifies.
        Never raises — scan errors must not crash the scheduler scan loop.
        """
        if (min_ask_diff is None or entry_window_sec is None
                or fav_price_min is None or fav_price_max is None):
            try:
                cfg = get_settings()
                if min_ask_diff is None:
                    min_ask_diff = cfg.LATE_ENTRY_MIN_ASK_DIFF
                if entry_window_sec is None:
                    entry_window_sec = cfg.LATE_ENTRY_WINDOW_SEC
                if fav_price_min is None:
                    fav_price_min = cfg.LATE_ENTRY_FAV_PRICE_MIN
                if fav_price_max is None:
                    fav_price_max = cfg.LATE_ENTRY_FAV_PRICE_MAX
            except Exception:
                if min_ask_diff is None:
                    min_ask_diff = MIN_ASK_DIFF
                if entry_window_sec is None:
                    entry_window_sec = ENTRY_WINDOW_SEC
                if fav_price_min is None:
                    fav_price_min = 0.50
                if fav_price_max is None:
                    fav_price_max = FAV_PRICE_MAX

        timeframe = getattr(user_context, "selected_timeframe", None)
        assets = getattr(user_context, "selected_assets", ()) or None

        try:
            markets = await pm.get_crypto_window_markets(timeframe or "5m", assets)
        except Exception as exc:
            log.warning("late_entry_v3 scan: get_crypto_window_markets failed", err=str(exc))
            return []

        if not markets:
            return []

        now = datetime.now(timezone.utc)
        blacklist = set(market_filters.blacklisted_market_ids)
        candidates: list[SignalCandidate] = []
        eligible = 0
        reject_counts: dict[str, int] = {}

        for m in markets:
            if not is_short_crypto_market(m, timeframe, assets):
                continue
            eligible += 1
            try:
                candidate, reject_reason = await _evaluate_market(
                    m,
                    blacklist=blacklist,
                    user_context=user_context,
                    strategy_name=self.name,
                    signal_ts=now,
                    now_ts=now.timestamp(),
                    min_ask_diff=min_ask_diff,
                    entry_window_sec=entry_window_sec,
                    fav_price_min=fav_price_min,
                    fav_price_max=fav_price_max,
                    min_entry_sec=min_entry_sec,
                    underdog_mode=underdog_mode,
                    force_exit_at_rem_sec=force_exit_at_rem_sec,
                    max_leg_spread=max_leg_spread,
                )
            except Exception as exc:
                log.debug("late_entry_v3 scan: skip market", err=str(exc))
                reject_counts["exception"] = reject_counts.get("exception", 0) + 1
                continue
            if candidate is not None:
                candidates.append(candidate)
                log.info(
                    "late_entry_v3 candidate",
                    slug=m.get("slug", ""),
                    side=candidate.side,
                    entry_price=candidate.metadata.get("entry_price", candidate.metadata.get("fav_price", 0)),
                    diff=candidate.metadata.get("ask_diff", 0),
                    secs=candidate.metadata.get("seconds_to_close", 0),
                    size=candidate.suggested_size_usdc,
                    underdog=candidate.metadata.get("underdog_mode", False),
                )
            elif reject_reason:
                reject_counts[reject_reason] = reject_counts.get(reject_reason, 0) + 1

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        log.info(
            "late_entry_v3 scan_summary",
            markets=len(markets),
            eligible=eligible,
            candidates=len(candidates),
            gate_rejects=reject_counts,
            min_ask_diff=min_ask_diff,
            window_sec=entry_window_sec,
            fav_price_min=fav_price_min,
            fav_price_max=fav_price_max,
            min_entry_sec=min_entry_sec,
            underdog=underdog_mode,
        )
        return candidates

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Per-tick exit hook: Kreo-style fixed-time exit, then flip-stop.

        Two-stage check:

        1. **Fixed-time exit** (Kreo parity): if the exit_watcher passes
           ``force_exit_at_rem_sec`` (preset+timeframe lookup) and
           ``seconds_to_close`` (derived from ``resolution_at``), close as soon
           as the candle's remaining seconds drop to the threshold. safe_close
           5m exits at rem=30s (= elapsed 270s) so the position is OUT before
           the noisy final 30s where SL gets hit at random.

        2. **Flip-stop** (existing): exit when the favored side's live price has
           collapsed below ``LATE_ENTRY_FLIP_STOP`` (default 0.10, near-disabled
           for close_sweep so it holds to resolution).

        ``position['current_price']`` is the live mark for the position's side,
        injected by the exit watcher. When missing, neither gate fires and the
        watcher's TP/SL + market-expiry paths still protect the position.
        """
        # 1. Fixed-time exit. exit_watcher passes ``force_exit_at_rem_sec`` +
        #    ``seconds_to_close`` from the (preset, timeframe, resolution_at)
        #    triple; both must be present to fire. Threshold uses ≤ so an
        #    exact match (rem == threshold) closes immediately.
        force_at = position.get("force_exit_at_rem_sec")
        secs_left = position.get("seconds_to_close")
        if force_at is not None and secs_left is not None:
            try:
                _force_at = float(force_at)
                _secs_left = float(secs_left)
            except (TypeError, ValueError):
                _force_at = _secs_left = None  # type: ignore[assignment]
            if _force_at is not None and _secs_left is not None and _secs_left <= _force_at:
                return ExitDecision(
                    should_exit=True,
                    reason="strategy_exit",
                    metadata={
                        "force_exit_at_rem_sec": _force_at,
                        "seconds_to_close": _secs_left,
                        "trigger": "fixed_time_exit",
                    },
                )

        # 2. Flip-stop (existing behaviour, unchanged).
        try:
            flip_stop = get_settings().LATE_ENTRY_FLIP_STOP
        except Exception:
            flip_stop = FLIP_STOP_PRICE
        cur = position.get("current_price")
        try:
            price = float(cur) if cur is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and price <= flip_stop:
            return ExitDecision(
                should_exit=True,
                reason="strategy_exit",
                metadata={
                    "flip_stop_price": flip_stop,
                    "current_price": price,
                    "trigger": "flip_stop",
                },
            )
        return ExitDecision(should_exit=False, reason="hold")


def _coerce_str_list(val: Any) -> list[str]:
    """Gamma list fields (clobTokenIds) may arrive as a JSON string or a list."""
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (ValueError, TypeError):
            return []
    if isinstance(val, list):
        return [str(x) for x in val]
    return []


def _best_ask(book: dict[str, Any] | None) -> float | None:
    """Best (lowest-price) ask from a CLOB orderbook, or None when empty/malformed.

    Polymarket's CLOB /book returns ``asks`` sorted by price DESCENDING (worst
    first), so ``asks[0]`` is the HIGHEST ask — using it priced both sides near
    1.0 and the strategy never qualified. Scan every level and take the minimum
    positive price so the true best ask is used regardless of ordering.
    """
    if not isinstance(book, dict):
        return None
    best: float | None = None
    for a in (book.get("asks") or []):
        try:
            p = float(a["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if p > 0.0 and (best is None or p < best):
            best = p
    return best


def _best_bid(book: dict[str, Any] | None) -> float | None:
    """Best (highest-price) bid from a CLOB orderbook, or None when empty/malformed.

    Same scan-and-pick pattern as ``_best_ask`` — never trust the array
    ordering. The best bid is the HIGHEST price someone is willing to pay,
    so it's the max of the positive bid prices. Used by the close_sweep
    per-leg spread gate to compute (best_ask - best_bid) per side.
    """
    if not isinstance(book, dict):
        return None
    best: float | None = None
    for b in (book.get("bids") or []):
        try:
            p = float(b["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if p > 0.0 and (best is None or p > best):
            best = p
    return best


def _book_depth_usdc(book: dict[str, Any] | None) -> float:
    """Total bid-side depth in USDC from a CLOB orderbook.

    Candle markets are not tracked by Gamma's liquidity aggregator, so
    ``markets.liquidity_usdc`` is near-zero after upsert. The risk gate
    (step 11) uses ``market_liquidity`` from the TradeSignal, which defaults
    to the DB value and rejects every candle candidate with
    ``insufficient_liquidity``. Computing depth from the live CLOB book
    (sum of bid size × price) gives the true available liquidity and lets
    the gate evaluate correctly.

    Returns 0.0 on any failure — callers treat 0 as "unknown, use DB value".
    """
    if not isinstance(book, dict):
        return 0.0
    total = 0.0
    for b in (book.get("bids") or []):
        try:
            total += float(b["price"]) * float(b["size"])
        except (KeyError, TypeError, ValueError):
            continue
    for a in (book.get("asks") or []):
        try:
            # Ask depth in USDC: cost to fill = (1 - ask_price) × size
            total += (1.0 - float(a["price"])) * float(a["size"])
        except (KeyError, TypeError, ValueError):
            continue
    return total


def _seconds_to_close(m: dict[str, Any], now_ts: float) -> float | None:
    """Seconds until the candle resolves.

    Primary: parse the market's end timestamp. Fallback: derive it from the
    recurring-candle slug ``{coin}-updown-{tf}-{slot}`` as ``slot + step``.
    Returns None when neither source yields a usable time.
    """
    end_iso = m.get("endDate") or m.get("endDateIso") or m.get("end_date_iso")
    if end_iso:
        try:
            dt = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() - now_ts
        except (ValueError, TypeError):
            pass

    slug = str(m.get("slug") or "")
    parts = slug.rsplit("-", 2)
    if len(parts) == 3:
        tf, slot_str = parts[1], parts[2]
        step = _TF_STEP_SECONDS.get(tf)
        if step is not None:
            try:
                return (int(slot_str) + step) - now_ts
            except (ValueError, TypeError):
                pass
    return None


async def _evaluate_market(
    m: dict[str, Any] | None,
    *,
    blacklist: set[str],
    user_context: UserContext,
    strategy_name: str,
    signal_ts: datetime,
    now_ts: float,
    min_ask_diff: float = MIN_ASK_DIFF,
    entry_window_sec: float = ENTRY_WINDOW_SEC,
    fav_price_min: float = 0.50,
    fav_price_max: float = FAV_PRICE_MAX,
    min_entry_sec: float | None = None,
    underdog_mode: bool = False,
    force_exit_at_rem_sec: float | None = None,
    max_leg_spread: float | None = None,
) -> tuple[SignalCandidate | None, str | None]:
    """Return (candidate, None) on success or (None, reject_reason) on any gate failure.

    ``min_entry_sec``: lower bound on seconds_left — skip if candle is too close to
    close (safe_close 30s floor: don't enter in the final 30s).
    ``underdog_mode``: enter the cheap side [fav_price_min, fav_price_max] instead
    of the majority side. flip_hunter uses this for asymmetric flip upside.
    """
    if not isinstance(m, dict):
        return None, "invalid_market"

    # BUG 1 FIX: use conditionId as canonical market_id (markets table PK).
    # Gamma's "id" field is a separate UUID that does NOT match the DB PK.
    # _load_market(cand.market_id) keys on conditionId — using the UUID caused
    # every candidate to be skipped as "skipped_market_not_synced".
    condition_id = str(
        m.get("conditionId") or m.get("condition_id") or m.get("conditionID") or ""
    )
    if not condition_id:
        log.debug("late_entry_v3 skip: no conditionId", slug=m.get("slug", ""))
        return None, "no_condition_id"
    market_id = condition_id  # canonical DB key

    if condition_id in blacklist:
        return None, "blacklisted"

    slug = str(m.get("slug") or "")
    is_candle = "updown" in slug

    # BUG 3 FIX: skip active check for crypto candle markets.
    # Polymarket sets active=False on candle markets shortly before resolution
    # while the CLOB book still has liquidity and orders. Relying on closed +
    # acceptingOrders is sufficient; the active flag kills every in-window candidate.
    if m.get("closed"):
        log.debug("late_entry_v3 skip closed", slug=slug)
        return None, "closed"
    if not is_candle and not m.get("active"):
        log.debug("late_entry_v3 skip inactive (non-candle)", slug=slug)
        return None, "inactive"
    if not m.get("acceptingOrders", m.get("accepting_orders", True)):
        log.debug("late_entry_v3 skip not_accepting_orders", slug=slug)
        return None, "not_accepting_orders"

    # Timing gate — only act inside the configured window before candle close.
    seconds_left = _seconds_to_close(m, now_ts)
    if seconds_left is None or seconds_left <= 0 or seconds_left > entry_window_sec:
        log.debug(
            "late_entry_v3 skip timing",
            slug=slug, secs=seconds_left, window=entry_window_sec,
        )
        return None, "outside_window"
    # Lower bound: safe_close skips the final <30s to avoid last-second fills.
    if min_entry_sec is not None and seconds_left < min_entry_sec:
        log.debug(
            "late_entry_v3 skip inside_min",
            slug=slug, secs=seconds_left, min=min_entry_sec,
        )
        return None, "inside_min_entry_sec"

    tokens = _coerce_str_list(m.get("clobTokenIds")) or _coerce_str_list(m.get("tokenIds"))
    if len(tokens) < 2 or not tokens[0] or not tokens[1]:
        log.debug("late_entry_v3 skip no_tokens", slug=slug)
        return None, "no_tokens"
    yes_token, no_token = tokens[0], tokens[1]

    yes_book, no_book = await asyncio.gather(
        pm.get_book(yes_token), pm.get_book(no_token)
    )
    yes_ask = _best_ask(yes_book)
    no_ask = _best_ask(no_book)
    if yes_ask is None or no_ask is None:
        log.debug(
            "late_entry_v3 skip empty_book",
            slug=slug, yes_ask=yes_ask, no_ask=no_ask,
        )
        return None, "empty_book"

    # Per-leg bid-ask spread (WARP/R00T/close-sweep-spread-gate, Lane 2/5).
    # Scoped to close_sweep via the `max_leg_spread` parameter: the preset
    # fires in the final ~35s before candle close where book depth thins
    # and a wide per-leg spread = high slippage on the taker fill. safe_close
    # and flip_hunter pass max_leg_spread=None (no-op) — they entry earlier
    # in the candle where this risk is lower and the existing complete-set
    # `spread` check (yes_ask + no_ask vs MAX_SPREAD) is sufficient.
    yes_bid = _best_bid(yes_book)
    no_bid = _best_bid(no_book)
    leg_spread_yes = (yes_ask - yes_bid) if yes_bid is not None else None
    leg_spread_no = (no_ask - no_bid) if no_bid is not None else None
    if max_leg_spread is not None and max_leg_spread > 0:
        if leg_spread_yes is None or leg_spread_no is None:
            log.debug(
                "late_entry_v3 skip leg_spread_missing_bid",
                slug=slug, yes_bid=yes_bid, no_bid=no_bid,
            )
            return None, "leg_spread_missing_bid"
        if leg_spread_yes > max_leg_spread or leg_spread_no > max_leg_spread:
            log.debug(
                "late_entry_v3 skip leg_spread_too_wide",
                slug=slug,
                yes_spread=leg_spread_yes,
                no_spread=leg_spread_no,
                max=max_leg_spread,
            )
            return None, "leg_spread_too_wide"

    # CLOB-derived liquidity: sum of bid depth across both sides.
    # Gamma's liquidity field is near-zero for candle markets (not tracked by
    # their aggregator), so the risk gate step 11 would reject every candidate
    # using the DB-cached value. Passing the live CLOB depth through metadata
    # lets _build_trade_signal override market_liquidity with a real value.
    clob_liquidity = _book_depth_usdc(yes_book) + _book_depth_usdc(no_book)

    spread = yes_ask + no_ask
    ask_diff = abs(yes_ask - no_ask)
    # Majority side — always the higher-priced side.
    fav_side = "YES" if yes_ask > no_ask else "NO"
    fav_price = max(yes_ask, no_ask)

    if ask_diff < min_ask_diff:
        log.debug(
            "late_entry_v3 skip low_ask_diff",
            slug=slug, diff=ask_diff, min=min_ask_diff,
        )
        return None, "low_ask_diff"
    if spread <= 0 or spread > MAX_SPREAD:
        log.debug(
            "late_entry_v3 skip spread",
            slug=slug, spread=spread, max=MAX_SPREAD,
        )
        return None, "spread_out_of_range"

    # Entry side and price gate.
    # Standard mode: enter the majority (favored) side; price must be ≥ fav_price_min.
    # Underdog mode (flip_hunter): enter the cheap side priced in [fav_price_min, fav_price_max].
    if underdog_mode:
        entry_side = "NO" if fav_side == "YES" else "YES"
        entry_price = min(yes_ask, no_ask)
    else:
        entry_side = fav_side
        entry_price = fav_price

    if entry_price < fav_price_min:
        log.debug(
            "late_entry_v3 skip entry_price_too_low",
            slug=slug, price=entry_price, min=fav_price_min, underdog=underdog_mode,
        )
        return None, "fav_price_too_low"

    if entry_price >= fav_price_max:
        log.debug(
            "late_entry_v3 skip entry_price_too_high",
            slug=slug, price=entry_price, max=fav_price_max, underdog=underdog_mode,
        )
        return None, "fav_price_too_high"

    confidence = max(0.0, min(ask_diff, 1.0))

    # Size off equity (free balance + open-position value), not just free cash,
    # so the deployable pool reflects the whole account. Fall back to free
    # balance when equity is not supplied (older callers / tests).
    size_base = user_context.equity_usdc or user_context.available_balance_usdc
    ceiling = resolve_per_trade_ceiling(
        size_base,
        getattr(user_context, "max_per_trade_mode", None),
        getattr(user_context, "max_per_trade_usdc", None),
        getattr(user_context, "max_per_trade_pct", None),
    )
    flip_stop = FLIP_STOP_PRICE  # module default; evaluate_exit reads from config
    suggested = suggested_trade_size(
        size_base, user_context.capital_allocation_pct, ceiling_usdc=ceiling,
    )

    # WARP/R00T/tob-freshness-gate: stamp the wall-clock at which the orderbook
    # snapshot (yes_ask / no_ask / entry_price) was finalized. Read by
    # services.signal_scan.signal_scan_job._process_candidate as step 3b-0 to
    # reject the candidate when scan->fill latency exceeds TOB_STALE_MS.
    entry_price_ts = datetime.now(timezone.utc).timestamp()

    return SignalCandidate(
        market_id=market_id,
        condition_id=condition_id,
        side=entry_side,
        confidence=confidence,
        suggested_size_usdc=suggested,
        strategy_name=strategy_name,
        signal_ts=signal_ts,
        metadata={
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "yes_bid": yes_bid,
            "no_bid": no_bid,
            "leg_spread_yes": leg_spread_yes,
            "leg_spread_no": leg_spread_no,
            "fav_price": fav_price,
            "entry_price": entry_price,
            "entry_price_ts": entry_price_ts,
            "underdog_mode": underdog_mode,
            "ask_diff": ask_diff,
            "spread": spread,
            "seconds_to_close": seconds_left,
            "flip_stop_price": flip_stop,
            "clob_liquidity": clob_liquidity,
            # Entry-price band the candidate satisfied at scan time. Re-checked
            # in _process_candidate against the live fill price so candle drift
            # between scan and fill cannot place the trade outside the band.
            "fav_price_min": fav_price_min,
            "fav_price_max": fav_price_max,
            # Kreo-style fixed-time exit: close when candle's remaining seconds
            # drop to this value (e.g. safe_close 30s exits BEFORE the noisy
            # final 30s; flip_hunter 5m 160s exits at the end of the early
            # entry window). None = no time-based exit (close_sweep holds to
            # candle resolution). Read by evaluate_exit at exit_watcher tick.
            "force_exit_at_rem_sec": force_exit_at_rem_sec,
            "reason": (
                f"late_entry: {entry_side} {'underdog' if underdog_mode else 'fav'} "
                f"{entry_price:.2f}, diff {ask_diff:.2f}, "
                f"spread {spread:.2f}, {seconds_left:.0f}s to close"
            ),
        },
        reasoning=(
            f"Late entry {entry_side} ({'underdog' if underdog_mode else 'favored'}) "
            f"price {entry_price:.2f}, ask-diff {ask_diff:.2f}, "
            f"{seconds_left:.0f}s to close, conf={confidence:.0%}."
        ),
    ), None


# Static fallback for force_exit_at_rem_sec_for() when get_settings() fails
# (e.g. test environments without a .env). Kept in sync with the config.py
# defaults so the helper produces sensible values even without live config.
_FORCE_EXIT_STATIC: dict[str, dict[str, float]] = {
    "safe_close": {"5m": 30.0, "15m": 30.0},
    "flip_hunter": {"5m": 160.0, "15m": 480.0},
    # close_sweep now force-exits ~8s before resolution (Kreo "exit at 299s"),
    # evaluated by the dedicated fast exit loop. TP/SL still exit earlier.
    "close_sweep": {"5m": 8.0, "15m": 8.0},
}


def force_exit_at_rem_sec_for(
    active_preset: str | None,
    timeframe: str | None,
) -> float | None:
    """Look up the Kreo-style fixed-time exit threshold for (preset, timeframe).

    Returns the remaining-seconds threshold at or below which the position
    should be force-closed by ``evaluate_exit``. Returns ``None`` when the
    preset/timeframe combination has no fixed-time exit configured (e.g.
    close_sweep holds to candle resolution; unknown presets are pass-through).

    Used by:
      * signal_scan_job during the entry scan to seed candidate metadata
        (so a candidate created mid-tick carries its own exit threshold).
      * exit_watcher when enriching the position dict for evaluate_exit
        (so a position whose preset was set after entry still gets the rule).

    Centralising the lookup here keeps the (preset, timeframe) → rem_sec map
    in one place — no duplicated literals between the entry and exit paths.
    Falls back to ``_FORCE_EXIT_STATIC`` if ``get_settings()`` raises so the
    helper produces sensible values in test environments without a .env.
    """
    if not active_preset:
        return None
    tf = (timeframe or "5m").lower()
    try:
        cfg = get_settings()
        if active_preset == "safe_close":
            # Same rem threshold for both 5m and 15m — Kreo exits at elapsed
            # 270s (5m) / 870s (15m), both yielding rem=30s.
            return float(cfg.PRESET_SAFE_CLOSE_FORCE_EXIT_REM_SEC)
        if active_preset == "flip_hunter":
            if tf == "15m":
                return float(cfg.PRESET_FLIP_HUNTER_15M_FORCE_EXIT_REM_SEC)
            return float(cfg.PRESET_FLIP_HUNTER_5M_FORCE_EXIT_REM_SEC)
        if active_preset == "close_sweep":
            # Exit ~8s before resolution (Kreo "exit at 299s"); same for 5m/15m.
            return float(cfg.PRESET_CLOSE_SWEEP_FORCE_EXIT_REM_SEC)
    except Exception:
        static = _FORCE_EXIT_STATIC.get(active_preset)
        if static is None:
            return None
        return static.get(tf, static["5m"])
    # any other preset: hold to candle resolution.
    return None


__all__ = [
    "LateEntryV3Strategy",
    "suggested_trade_size",
    "resolve_per_trade_ceiling",
    "force_exit_at_rem_sec_for",
]
