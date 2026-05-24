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
MIN_ASK_DIFF: float = 0.30        # require a clearly favored side
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
    ) -> list[SignalCandidate]:
        """Emit one favored-side candidate per in-window crypto candle market.

        Returns an empty list on any failure or when no market qualifies.
        Never raises — scan errors must not crash the scheduler scan loop.
        """
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

        for m in markets:
            if not is_short_crypto_market(m, timeframe, assets):
                continue
            try:
                candidate = await _evaluate_market(
                    m,
                    blacklist=blacklist,
                    user_context=user_context,
                    strategy_name=self.name,
                    signal_ts=now,
                    now_ts=now.timestamp(),
                )
            except Exception as exc:
                logger.debug("late_entry_v3 scan: skip market err=%s", exc)
                continue
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Flip-stop: exit when the favored side's live price has flipped down.

        ``position['current_price']`` is the live mark for the position's side,
        injected by the exit watcher. When it is missing we hold (the watcher's
        TP/SL and market-expiry paths still protect the position).
        """
        cur = position.get("current_price")
        try:
            price = float(cur) if cur is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and price <= FLIP_STOP_PRICE:
            return ExitDecision(
                should_exit=True,
                reason="strategy_exit",
                metadata={"flip_stop_price": FLIP_STOP_PRICE, "current_price": price},
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
    """Top-of-book ask price from a CLOB orderbook, or None when empty/malformed."""
    if not isinstance(book, dict):
        return None
    asks = book.get("asks") or []
    if not asks:
        return None
    try:
        return float(asks[0]["price"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


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
) -> SignalCandidate | None:
    """Return a SignalCandidate for the favored side, or None if any gate fails."""
    if not isinstance(m, dict):
        return None

    market_id = str(m.get("id") or "")
    condition_id = str(
        m.get("conditionId") or m.get("condition_id") or m.get("conditionID") or ""
    )
    if not market_id or not condition_id:
        return None
    if condition_id in blacklist or market_id in blacklist:
        return None

    if not m.get("active") or m.get("closed"):
        return None
    if not m.get("acceptingOrders", m.get("accepting_orders", True)):
        return None

    # Timing gate — only act inside the final window before the candle closes.
    seconds_left = _seconds_to_close(m, now_ts)
    if seconds_left is None or seconds_left <= 0 or seconds_left > ENTRY_WINDOW_SEC:
        return None

    tokens = _coerce_str_list(m.get("clobTokenIds")) or _coerce_str_list(m.get("tokenIds"))
    if len(tokens) < 2 or not tokens[0] or not tokens[1]:
        return None
    yes_token, no_token = tokens[0], tokens[1]

    yes_book, no_book = await asyncio.gather(
        pm.get_book(yes_token), pm.get_book(no_token)
    )
    yes_ask = _best_ask(yes_book)
    no_ask = _best_ask(no_book)
    if yes_ask is None or no_ask is None:
        return None

    spread = yes_ask + no_ask
    ask_diff = abs(yes_ask - no_ask)
    favored = "YES" if yes_ask > no_ask else "NO"
    fav_price = max(yes_ask, no_ask)

    if ask_diff < MIN_ASK_DIFF:
        return None
    if spread <= 0 or spread > MAX_SPREAD:
        return None
    if fav_price >= FAV_PRICE_MAX:
        return None

    confidence = max(0.0, min(ask_diff, 1.0))

    allocated = user_context.available_balance_usdc * user_context.capital_allocation_pct
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
            "flip_stop_price": FLIP_STOP_PRICE,
            "reason": (
                f"late_entry: {favored} fav {fav_price:.2f}, diff {ask_diff:.2f}, "
                f"spread {spread:.2f}, {seconds_left:.0f}s to close"
            ),
        },
        reasoning=(
            f"Late entry {favored}: favored ask {fav_price:.2f}, ask-diff {ask_diff:.2f}, "
            f"{seconds_left:.0f}s to close, conf={confidence:.0%}."
        ),
    )


__all__ = ["LateEntryV3Strategy"]
