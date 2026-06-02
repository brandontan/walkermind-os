"""Complete-set arbitrage — detection + sizing core (Lane 1 of the
complete-set-arb epic).

Edge thesis: a Polymarket binary candle market's YES and NO outcome tokens settle
to a combined $1.00 (one side redeems $1, the other $0). If the live CLOB lets you
*take* ``y`` shares of YES and ``y`` shares of NO for a combined cost below
``y * $1.00``, holding the complete set to resolution locks a riskless profit of
``y * 1.00 - cost`` (minus fees), regardless of which side wins.

The catch (why this is rare): market-makers normally quote YES_ask + NO_ask **above**
$1.00 (the vig), so a fillable arb only appears in fleeting dislocations and is
bounded by the thin depth at those prices. This module measures the *fillable* size
by walking real order-book levels — not the top-of-book quote — so the number
reflects what could actually be executed.

SCOPE (Lane 1): pure, synchronous, IO-free detection + sizing. This module does NOT
place orders, fetch books, touch the risk gate, or register a strategy. It is the
tested foundation the Lane-2 execution path will consume. Per CLAUDE.md it ships
unwired (zero runtime risk) so the level-walking math can be proven in isolation
first.

Pipeline boundary (target, Lane 2+):
    DATA -> [SIGNAL: complete-set detector <-- this file] -> RISK -> EXECUTION (two-leg)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# A Polymarket complete set (1 YES + 1 NO) redeems to exactly this at resolution.
COMPLETE_SET_PAYOUT: float = 1.0


@dataclass(frozen=True)
class CompleteSetQuote:
    """A fillable complete-set arbitrage opportunity at a point in time.

    All sizes are in outcome-token shares; all costs in USDC. ``net_margin_usdc``
    is the locked profit after the caller-supplied per-pair margin buffer (which
    folds in fees/slippage tolerance) — it is always >= 0 for a returned quote.
    """

    market_id: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    fillable_shares: float          # y — pairs buyable while each pair stays profitable
    yes_cost_usdc: float            # cost to take ``y`` YES shares (cheapest levels)
    no_cost_usdc: float             # cost to take ``y`` NO shares (cheapest levels)
    avg_pair_cost: float            # (yes_cost + no_cost) / y  — < COMPLETE_SET_PAYOUT
    gross_margin_usdc: float        # y * COMPLETE_SET_PAYOUT - (yes_cost + no_cost)
    net_margin_usdc: float          # gross minus the per-pair margin buffer * y
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_cost_usdc(self) -> float:
        return self.yes_cost_usdc + self.no_cost_usdc


def _asks_ascending(book: dict[str, Any] | None) -> list[tuple[float, float]]:
    """Return [(price, size), ...] asks sorted cheapest-first, strictly inside (0,1).

    Polymarket's CLOB ``/book`` returns ``asks`` sorted by price DESCENDING (worst
    first), and prices may arrive as strings — never trust the ordering, and skip
    any degenerate level (non-numeric, price <= 0, price >= 1, size <= 0) so the
    walk below only consumes real, takeable liquidity.
    """
    if not isinstance(book, dict):
        return []
    out: list[tuple[float, float]] = []
    for a in (book.get("asks") or []):
        try:
            price = float(a["price"])
            size = float(a["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 < price < 1.0 and size > 0.0:
            out.append((price, size))
    out.sort(key=lambda lvl: lvl[0])
    return out


def fillable_complete_set(
    yes_book: dict[str, Any] | None,
    no_book: dict[str, Any] | None,
    *,
    market_id: str,
    condition_id: str,
    yes_token_id: str,
    no_token_id: str,
    min_pair_margin: float,
    min_shares: float = 1.0,
    max_shares: float | None = None,
) -> CompleteSetQuote | None:
    """Walk both books to size the largest *profitable* complete-set buy.

    Buys ``y`` shares of YES and ``y`` shares of NO from the cheapest levels. The
    marginal cost of the i-th pair is ``yes_ask_level + no_ask_level`` and is
    non-decreasing as we eat deeper, so the profitable pairs form a prefix: include
    each matched chunk while its marginal pair cost leaves at least
    ``min_pair_margin`` of profit (``1.0 - marginal_cost >= min_pair_margin``), and
    stop at the first chunk that does not. ``min_pair_margin`` is the caller's net
    floor — fold fee + slippage tolerance into it.

    Args:
        min_pair_margin: minimum locked profit per pair, in USDC (e.g. 0.01 = 1c).
            Must be > 0; a 0/negative floor would accept break-even noise.
        min_shares: reject the opportunity if fewer than this many pairs are
            fillable (avoids dust trades).
        max_shares: optional cap (e.g. from per-trade size ceiling / available
            capital expressed in shares); ``None`` = no cap.

    Returns a ``CompleteSetQuote`` when a profitable, large-enough set is fillable,
    else ``None``. Never raises — a malformed book yields ``None``.
    """
    if min_pair_margin <= 0.0:
        # Defensive: a non-positive margin floor would book break-even/noise as
        # "arb". Treat as misconfiguration → no opportunity rather than raise.
        log.warning("complete_set: non-positive min_pair_margin", value=min_pair_margin)
        return None

    ya = _asks_ascending(yes_book)
    na = _asks_ascending(no_book)
    if not ya or not na:
        return None

    threshold = COMPLETE_SET_PAYOUT - min_pair_margin  # max acceptable marginal pair cost

    yi = ni = 0
    ya_rem = ya[0][1]
    na_rem = na[0][1]
    shares = 0.0
    yes_cost = 0.0
    no_cost = 0.0

    while yi < len(ya) and ni < len(na):
        yp = ya[yi][0]
        np_ = na[ni][0]
        if yp + np_ > threshold:
            break  # first unprofitable marginal pair — prefix is complete
        chunk = min(ya_rem, na_rem)
        if max_shares is not None:
            remaining_cap = max_shares - shares
            if remaining_cap <= 0.0:
                break
            chunk = min(chunk, remaining_cap)
        if chunk <= 0.0:
            break
        shares += chunk
        yes_cost += chunk * yp
        no_cost += chunk * np_
        ya_rem -= chunk
        na_rem -= chunk
        if ya_rem <= 0.0:
            yi += 1
            if yi < len(ya):
                ya_rem = ya[yi][1]
        if na_rem <= 0.0:
            ni += 1
            if ni < len(na):
                na_rem = na[ni][1]
        if max_shares is not None and shares >= max_shares:
            break

    if shares < min_shares:
        return None

    total_cost = yes_cost + no_cost
    gross = shares * COMPLETE_SET_PAYOUT - total_cost
    net = gross - min_pair_margin * shares
    if net <= 0.0:
        # Should not happen given the per-pair threshold, but guard against
        # float drift on tiny sizes — never report a non-profitable quote.
        return None

    return CompleteSetQuote(
        market_id=market_id,
        condition_id=condition_id,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        fillable_shares=round(shares, 6),
        yes_cost_usdc=round(yes_cost, 6),
        no_cost_usdc=round(no_cost, 6),
        avg_pair_cost=round(total_cost / shares, 6),
        gross_margin_usdc=round(gross, 6),
        net_margin_usdc=round(net, 6),
    )


__all__ = ["CompleteSetQuote", "fillable_complete_set", "COMPLETE_SET_PAYOUT"]
