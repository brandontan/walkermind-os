"""core/signal/signal_engine — Edge-based signal generation with EV and Kelly sizing.

Pipeline::

    markets (list of market dicts)
        │  each dict: {market_id, p_market, p_model, liquidity_usd, bankroll, ...}
        ▼
    generate_signals()
        ├─ edge = p_model - p_market
        ├─ filter: edge > EDGE_THRESHOLD (0.02)
        ├─ filter: liquidity_usd > MIN_LIQUIDITY_USD (10_000)
        ├─ ev  = p_model * b - (1 - p_model)       where b = 1/p_market - 1
        ├─ kelly_f = (p*b - q) / b                 full Kelly
        ├─ size = bankroll * KELLY_FRACTION * kelly_f   clamped at MAX_POSITION_PCT
        └─ returns list of SignalResult

Environment variables:
    EDGE_THRESHOLD       — minimum edge required (default 0.02)
    MIN_LIQUIDITY_USD    — minimum market liquidity in USD (default 10_000)
    KELLY_FRACTION       — fractional Kelly multiplier (default 0.25)
    MAX_POSITION_PCT     — maximum position as fraction of bankroll (default 0.10)
    DEFAULT_BANKROLL_USD — default bankroll when not provided per-market (default 10_000)

Constants (not overridable via env):
    PRICE_MIN = 0.05 — markets priced below this are skipped (near-impossible)
    PRICE_MAX = 0.95 — markets priced above this are skipped (near-certain)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Configuration ─────────────────────────────────────────────────────────────

_EDGE_THRESHOLD: float = float(os.getenv("EDGE_THRESHOLD", "0.02"))
_MIN_LIQUIDITY_USD: float = float(os.getenv("MIN_LIQUIDITY_USD", "10000.0"))
_KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.25"))
_MAX_POSITION_PCT: float = float(os.getenv("MAX_POSITION_PCT", "0.10"))
_DEFAULT_BANKROLL_USD: float = float(os.getenv("DEFAULT_BANKROLL_USD", "10000.0"))
_PRICE_MIN: float = 0.05
_PRICE_MAX: float = 0.95


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class SignalResult:
    """A generated trading signal with edge, EV, and sizing information.

    Attributes:
        market_id: Polymarket condition ID.
        side: "YES" or "NO" — the direction to trade.
        p_market: Market-implied probability (current best price).
        p_model: Model-estimated true probability.
        edge: p_model - p_market (positive only).
        ev: Expected value of the trade.
        kelly_f: Full Kelly fraction before scaling.
        size_usd: Recommended position size in USD (fractional Kelly, clamped).
        liquidity_usd: Available market liquidity at signal time.
        extra: Additional market context passed through from input.
    """

    market_id: str
    side: str
    p_market: float
    p_model: float
    edge: float
    ev: float
    kelly_f: float
    size_usd: float
    liquidity_usd: float
    extra: dict = field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _calculate_ev(p_model: float, p_market: float) -> float:
    """Compute expected value for a binary YES bet.

    EV = p_model * b - (1 - p_model)   where b = 1/p_market - 1 (decimal odds - 1)

    Args:
        p_model: Model probability of YES (0–1).
        p_market: Market-implied probability / current price of YES (0–1).

    Returns:
        Expected value. Positive means the bet has positive edge.
    """
    if p_market <= 0.0:
        return 0.0
    b = (1.0 / p_market) - 1.0
    return p_model * b - (1.0 - p_model)


def _calculate_kelly(p: float, b: float) -> float:
    """Compute full Kelly fraction for a binary bet.

    kelly_f = (p * b - q) / b   where q = 1 - p

    Args:
        p: Model win probability.
        b: Net decimal odds (payout per unit wagered, e.g. 0.6 / 0.4 - 1).

    Returns:
        Full Kelly fraction. Clamped to [0, 1] — never negative.
    """
    if b <= 0.0:
        return 0.0
    q = 1.0 - p
    full_kelly = (p * b - q) / b
    if full_kelly > 0.5:
        log.warning(
            "kelly_fraction_high",
            full_kelly=round(full_kelly, 4),
            p=round(p, 4),
            b=round(b, 4),
            hint="High Kelly value may indicate model calibration issue",
        )
    return max(0.0, min(full_kelly, 1.0))


def _position_size(
    bankroll: float,
    kelly_f: float,
    kelly_fraction: float = _KELLY_FRACTION,
    max_position_pct: float = _MAX_POSITION_PCT,
) -> float:
    """Compute final position size applying fractional Kelly and max-position cap.

    size = bankroll * kelly_fraction * kelly_f
    Clamped to: max(0, min(size, bankroll * max_position_pct))

    Args:
        bankroll: Current account balance in USD.
        kelly_f: Full Kelly fraction (0–1).
        kelly_fraction: Fractional Kelly multiplier (default 0.25).
        max_position_pct: Max position as fraction of bankroll (default 0.10).

    Returns:
        Final position size in USD.
    """
    raw = bankroll * kelly_fraction * kelly_f
    cap = bankroll * max_position_pct
    return max(0.0, min(raw, cap))


# ── Main entry point ──────────────────────────────────────────────────────────


async def generate_signals(
    markets: list[dict],
    *,
    edge_threshold: Optional[float] = None,
    min_liquidity_usd: Optional[float] = None,
    kelly_fraction: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    default_bankroll_usd: Optional[float] = None,
) -> list[SignalResult]:
    """Generate trading signals for a list of markets.

    For each market dict the function:
      1. Reads ``p_market`` and ``p_model`` from the dict.
      2. Computes ``edge = p_model - p_market``.
      3. Skips markets where ``edge <= edge_threshold`` (default 0.02).
      4. Skips markets where ``liquidity_usd < min_liquidity_usd`` (default $10k).
      5. Computes EV and fractional Kelly position size.
      6. Returns a :class:`SignalResult` for every market that passes all filters.

    Expected market dict keys:
        market_id    (str)  — Polymarket condition ID (required)
        p_market     (float)— market-implied probability / current price
        p_model      (float)— model-estimated probability
        liquidity_usd(float)— total available liquidity in USD
        bankroll     (float)— current account bankroll (optional, uses default)
        side         (str)  — "YES" | "NO" (optional, derived from edge direction)

    Args:
        markets: List of market context dicts.
        edge_threshold: Override env EDGE_THRESHOLD.
        min_liquidity_usd: Override env MIN_LIQUIDITY_USD.
        kelly_fraction: Override env KELLY_FRACTION.
        max_position_pct: Override env MAX_POSITION_PCT.
        default_bankroll_usd: Override env DEFAULT_BANKROLL_USD.

    Returns:
        List of :class:`SignalResult` — one per market that passed all filters,
        in the same order as the input list.
    """
    _edge_thr = edge_threshold if edge_threshold is not None else _EDGE_THRESHOLD
    _min_liq = min_liquidity_usd if min_liquidity_usd is not None else _MIN_LIQUIDITY_USD
    _kf = kelly_fraction if kelly_fraction is not None else _KELLY_FRACTION
    _max_pos = max_position_pct if max_position_pct is not None else _MAX_POSITION_PCT
    _bankroll_default = (
        default_bankroll_usd if default_bankroll_usd is not None else _DEFAULT_BANKROLL_USD
    )

    signals: list[SignalResult] = []

    for market in markets:
        market_id: str = str(market.get("market_id", ""))
        p_market: float = float(market.get("p_market", 0.0))
        p_model: float = float(market.get("p_model", 0.0))
        liquidity_usd: float = float(market.get("liquidity_usd", 0.0))
        bankroll: float = float(market.get("bankroll", _bankroll_default))

        # ── Edge filter ───────────────────────────────────────────────────────
        edge: float = p_model - p_market

        if edge <= _edge_thr:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="low_edge",
                edge=round(edge, 4),
                threshold=_edge_thr,
            )
            continue

        # ── Liquidity filter ──────────────────────────────────────────────────
        if liquidity_usd < _min_liq:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="low_liquidity",
                liquidity_usd=liquidity_usd,
                min_liquidity_usd=_min_liq,
            )
            continue

        # ── Price sanity guard ────────────────────────────────────────────────
        if not (_PRICE_MIN <= p_market <= _PRICE_MAX):
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="price_out_of_range",
                p_market=p_market,
            )
            continue

        # ── EV calculation ────────────────────────────────────────────────────
        ev: float = _calculate_ev(p_model=p_model, p_market=p_market)

        # ── Kelly sizing ──────────────────────────────────────────────────────
        b: float = (1.0 / p_market) - 1.0
        kelly_f: float = _calculate_kelly(p=p_model, b=b)
        size_usd: float = _position_size(
            bankroll=bankroll,
            kelly_f=kelly_f,
            kelly_fraction=_kf,
            max_position_pct=_max_pos,
        )

        if size_usd <= 0.0:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="zero_size",
                kelly_f=round(kelly_f, 4),
                bankroll=bankroll,
            )
            continue

        side: str = str(market.get("side", "YES"))

        log.info(
            "signal_generated",
            market_id=market_id,
            side=side,
            p_market=round(p_market, 4),
            p_model=round(p_model, 4),
            edge=round(edge, 4),
            ev=round(ev, 4),
            kelly_f=round(kelly_f, 4),
            size_usd=round(size_usd, 2),
            liquidity_usd=liquidity_usd,
        )

        # Collect any extra keys the caller passed in (e.g. token_id, title)
        known_keys = {
            "market_id", "p_market", "p_model", "liquidity_usd", "bankroll", "side"
        }
        extra = {k: v for k, v in market.items() if k not in known_keys}

        signals.append(
            SignalResult(
                market_id=market_id,
                side=side,
                p_market=p_market,
                p_model=p_model,
                edge=edge,
                ev=ev,
                kelly_f=kelly_f,
                size_usd=size_usd,
                liquidity_usd=liquidity_usd,
                extra=extra,
            )
        )

    log.info(
        "signals_summary",
        total_markets=len(markets),
        signals_generated=len(signals),
        signals_skipped=len(markets) - len(signals),
    )

    return signals
