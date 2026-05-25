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
import logging
from datetime import datetime, timezone
from typing import Any

from ....config import get_settings
from ....integrations import polymarket as pm
from ..base import BaseStrategy
from ..eligibility import is_short_crypto_market
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

logger = logging.getLogger(__name__)

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
FAV_PRICE_MAX: float = 0.93       # skip when the favored side is already near 1.0
FLIP_STOP_PRICE: float = 0.48     # exit when favored side's live price <= this

DEFAULT_TP_PCT: float = 0.15
DEFAULT_SL_PCT: float = 0.08

# Window step seconds by timeframe — used to derive the candle close from the
# slug ({coin}-updown-{tf}-{slot}) when the market dict carries no end date.
_TF_STEP_SECONDS: dict[str, int] = {"5m": 300, "15m": 900}

# Suggested-size envelope (the gate re-sizes downward via Kelly + caps).
_SUGGESTED_SIZE_FRACTION: float = 0.04
_SUGGESTED_SIZE_MIN_USDC: float = 1.0
_SUGGESTED_SIZE_MAX_USDC: float = 25.0


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
    ) -> list[SignalCandidate]:
        """Emit one favored-side candidate per in-window crypto candle market.

        Callers (e.g. run_close_sweep_fast) may pass preset-specific overrides
        for min_ask_diff, entry_window_sec, and fav_price_min. When not
        provided, values fall back to global config / module defaults.

        Returns an empty list on any failure or when no market qualifies.
        Never raises — scan errors must not crash the scheduler scan loop.
        """
        if min_ask_diff is None or entry_window_sec is None or fav_price_min is None:
            try:
                cfg = get_settings()
                if min_ask_diff is None:
                    min_ask_diff = cfg.LATE_ENTRY_MIN_ASK_DIFF
                if entry_window_sec is None:
                    entry_window_sec = cfg.LATE_ENTRY_WINDOW_SEC
                if fav_price_min is None:
                    fav_price_min = cfg.LATE_ENTRY_FAV_PRICE_MIN
            except Exception:
                if min_ask_diff is None:
                    min_ask_diff = MIN_ASK_DIFF
                if entry_window_sec is None:
                    entry_window_sec = ENTRY_WINDOW_SEC
                if fav_price_min is None:
                    fav_price_min = 0.50

        timeframe = getattr(user_context, "selected_timeframe", None)
        assets = getattr(user_context, "selected_assets", ()) or None

        try:
            markets = await pm.get_crypto_window_markets(timeframe or "5m", assets)
        except Exception as exc:
            logger.warning("late_entry_v3 scan: get_crypto_window_markets failed err=%s", exc)
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
                )
            except Exception as exc:
                logger.debug("late_entry_v3 scan: skip market err=%s", exc)
                reject_counts["exception"] = reject_counts.get("exception", 0) + 1
                continue
            if candidate is not None:
                candidates.append(candidate)
                logger.info(
                    "late_entry_v3 candidate slug=%s side=%s fav=%.3f diff=%.3f secs=%.0f size=%.2f",
                    m.get("slug", ""),
                    candidate.side,
                    candidate.metadata.get("fav_price", 0),
                    candidate.metadata.get("ask_diff", 0),
                    candidate.metadata.get("seconds_to_close", 0),
                    candidate.suggested_size_usdc,
                )
            elif reject_reason:
                reject_counts[reject_reason] = reject_counts.get(reject_reason, 0) + 1

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        logger.info(
            "late_entry_v3 scan_summary markets=%d eligible=%d candidates=%d "
            "gate_rejects=%s min_ask_diff=%.3f window_sec=%.0f fav_price_min=%.2f",
            len(markets),
            eligible,
            len(candidates),
            reject_counts,
            min_ask_diff,
            entry_window_sec,
            fav_price_min,
        )
        return candidates

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Flip-stop: exit when the favored side's live price has flipped down.

        ``position['current_price']`` is the live mark for the position's side,
        injected by the exit watcher. When it is missing we hold (the watcher's
        TP/SL and market-expiry paths still protect the position).
        """
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
                metadata={"flip_stop_price": flip_stop, "current_price": price},
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
) -> tuple[SignalCandidate | None, str | None]:
    """Return (candidate, None) on success or (None, reject_reason) on any gate failure."""
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
        logger.debug("late_entry_v3 skip: no conditionId slug=%s", m.get("slug", ""))
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
        logger.debug("late_entry_v3 skip closed slug=%s", slug)
        return None, "closed"
    if not is_candle and not m.get("active"):
        logger.debug("late_entry_v3 skip inactive (non-candle) slug=%s", slug)
        return None, "inactive"
    if not m.get("acceptingOrders", m.get("accepting_orders", True)):
        logger.debug("late_entry_v3 skip not_accepting_orders slug=%s", slug)
        return None, "not_accepting_orders"

    # Timing gate — only act inside the final window before the candle closes.
    seconds_left = _seconds_to_close(m, now_ts)
    if seconds_left is None or seconds_left <= 0 or seconds_left > entry_window_sec:
        logger.debug(
            "late_entry_v3 skip timing slug=%s secs=%s window=%.0f",
            slug, seconds_left, entry_window_sec,
        )
        return None, "outside_window"

    tokens = _coerce_str_list(m.get("clobTokenIds")) or _coerce_str_list(m.get("tokenIds"))
    if len(tokens) < 2 or not tokens[0] or not tokens[1]:
        logger.debug("late_entry_v3 skip no_tokens slug=%s", slug)
        return None, "no_tokens"
    yes_token, no_token = tokens[0], tokens[1]

    yes_book, no_book = await asyncio.gather(
        pm.get_book(yes_token), pm.get_book(no_token)
    )
    yes_ask = _best_ask(yes_book)
    no_ask = _best_ask(no_book)
    if yes_ask is None or no_ask is None:
        logger.debug(
            "late_entry_v3 skip empty_book slug=%s yes_ask=%s no_ask=%s",
            slug, yes_ask, no_ask,
        )
        return None, "empty_book"

    # CLOB-derived liquidity: sum of bid depth across both sides.
    # Gamma's liquidity field is near-zero for candle markets (not tracked by
    # their aggregator), so the risk gate step 11 would reject every candidate
    # using the DB-cached value. Passing the live CLOB depth through metadata
    # lets _build_trade_signal override market_liquidity with a real value.
    clob_liquidity = _book_depth_usdc(yes_book) + _book_depth_usdc(no_book)

    spread = yes_ask + no_ask
    ask_diff = abs(yes_ask - no_ask)
    favored = "YES" if yes_ask > no_ask else "NO"
    fav_price = max(yes_ask, no_ask)

    if ask_diff < min_ask_diff:
        logger.debug(
            "late_entry_v3 skip low_ask_diff slug=%s diff=%.4f min=%.4f",
            slug, ask_diff, min_ask_diff,
        )
        return None, "low_ask_diff"
    if spread <= 0 or spread > MAX_SPREAD:
        logger.debug(
            "late_entry_v3 skip spread slug=%s spread=%.4f max=%.4f",
            slug, spread, MAX_SPREAD,
        )
        return None, "spread_out_of_range"

    # Favored side must be the majority-probability side (≥ fav_price_min).
    # When fav_price < 0.50 both sides are below 50¢ — the market is ambiguous
    # or the CLOB is thin. The flip-stop (0.48) would trigger immediately on
    # entry, producing a 13-second zero-PnL exit that confuses users.
    # fav_price_min is passed by the caller (preset-specific); default 0.50.
    if fav_price < fav_price_min:
        logger.debug(
            "late_entry_v3 skip fav_price_too_low slug=%s fav=%.4f min=%.4f",
            slug, fav_price, fav_price_min,
        )
        return None, "fav_price_too_low"

    if fav_price >= FAV_PRICE_MAX:
        logger.debug(
            "late_entry_v3 skip fav_too_high slug=%s fav=%.4f max=%.4f",
            slug, fav_price, FAV_PRICE_MAX,
        )
        return None, "fav_price_too_high"

    confidence = max(0.0, min(ask_diff, 1.0))

    allocated = user_context.available_balance_usdc * user_context.capital_allocation_pct
    flip_stop = FLIP_STOP_PRICE  # module default; evaluate_exit reads from config
    suggested = max(
        _SUGGESTED_SIZE_MIN_USDC,
        min(allocated * _SUGGESTED_SIZE_FRACTION, _SUGGESTED_SIZE_MAX_USDC),
    )

    return SignalCandidate(
        market_id=market_id,
        condition_id=condition_id,
        side=favored,
        confidence=confidence,
        suggested_size_usdc=suggested,
        strategy_name=strategy_name,
        signal_ts=signal_ts,
        metadata={
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "fav_price": fav_price,
            "ask_diff": ask_diff,
            "spread": spread,
            "seconds_to_close": seconds_left,
            "flip_stop_price": flip_stop,
            # Live CLOB bid depth (both sides combined). Used by _build_trade_signal
            # to override market_liquidity so gate 11 evaluates real depth instead
            # of the near-zero Gamma liquidity field stored in markets.liquidity_usdc.
            "clob_liquidity": clob_liquidity,
            "reason": (
                f"late_entry: {favored} fav {fav_price:.2f}, diff {ask_diff:.2f}, "
                f"spread {spread:.2f}, {seconds_left:.0f}s to close"
            ),
        },
        reasoning=(
            f"Late entry {favored}: favored ask {fav_price:.2f}, ask-diff {ask_diff:.2f}, "
            f"{seconds_left:.0f}s to close, conf={confidence:.0%}."
        ),
    ), None


__all__ = ["LateEntryV3Strategy"]
