"""core.signal.signal_engine — Edge-based signal generation pipeline.

For each market in the supplied list this module:

1. Reads ``p_market`` (the current market-implied probability) and
   ``p_model``   (the model's estimated probability).
2. Computes ``edge = p_model - p_market``.
3. Skips the market if ``edge <= 0`` (no positive edge).
4. Computes Expected Value: ``EV = p_model * b - (1 - p_model)``
   where ``b`` (decimal odds) is derived from the market price:
   ``b = (1 / p_market) - 1``.
5. Applies the signal filter — only continues when:
   - ``edge > EDGE_THRESHOLD``   (default 0.02, i.e. 2 %)
   - ``liquidity_usd > MIN_LIQUIDITY_USD``   (default $10,000)
6. Sizes the position using fractional Kelly:
   ``kelly_f = (p * b - q) / b``  (where q = 1 - p_model)
   ``size    = bankroll * KELLY_FRACTION * kelly_f``
   clamped to at most ``MAX_POSITION_FRACTION * bankroll``.
7. Emits a ``log.info("signal_generated", ...)`` event and appends the
   :class:`SignalResult` to the output list.

Environment variables (all optional):
    SIGNAL_EDGE_THRESHOLD     — minimum edge to generate signal (default 0.02)
    SIGNAL_MIN_LIQUIDITY_USD  — minimum liquidity required   (default 10000)
    SIGNAL_KELLY_FRACTION     — fractional-Kelly multiplier  (default 0.25)
    SIGNAL_MAX_POSITION_PCT   — max position as fraction of bankroll (default 0.10)

Usage::

    from core.signal import generate_signals

    signals = await generate_signals(markets, bankroll=5000.0)
    for s in signals:
        print(s.market_id, s.edge, s.size_usd)
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

import structlog

log = structlog.get_logger()

# ── Configuration defaults ─────────────────────────────────────────────────────

_EDGE_THRESHOLD: float = 0.02          # 2 % minimum edge
_MIN_LIQUIDITY_USD: float = 10_000.0   # $10,000 minimum market depth
_KELLY_FRACTION: float = 0.25          # fractional Kelly multiplier
_MAX_POSITION_FRACTION: float = 0.10   # max 10 % of bankroll per trade


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


# ── SignalResult dataclass ─────────────────────────────────────────────────────


@dataclass
class SignalResult:
    """A generated trading signal that has passed all filters.

    Attributes:
        signal_id:     Unique identifier (UUID4 hex prefix).
        market_id:     Polymarket condition ID.
        side:          "YES" or "NO" — direction of the trade.
        p_market:      Current market-implied probability.
        p_model:       Model-estimated probability.
        edge:          ``p_model - p_market`` (always positive here).
        ev:            Expected Value for the trade.
        kelly_f:       Raw (unscaled) Kelly fraction.
        size_usd:      Final position size in USD (Kelly-sized, clamped).
        liquidity_usd: Observed market liquidity at signal time.
        extra:         Any additional fields forwarded from the market dict.
    """

    signal_id: str
    market_id: str
    side: str
    p_market: float
    p_model: float
    edge: float
    ev: float
    kelly_f: float
    size_usd: float
    liquidity_usd: float
    extra: dict[str, Any] = field(default_factory=dict)


# ── Core logic ─────────────────────────────────────────────────────────────────


async def generate_signals(
    markets: Sequence[dict[str, Any]],
    bankroll: float = 1_000.0,
    edge_threshold: float | None = None,
    min_liquidity_usd: float | None = None,
    kelly_fraction: float | None = None,
    max_position_fraction: float | None = None,
) -> list[SignalResult]:
    """Evaluate a list of markets and return signals with positive edge.

    Each market dict is expected to contain at minimum:
        ``market_id``     — Polymarket condition ID (str)
        ``p_market``      — current market price / implied probability (float 0-1)
        ``p_model``       — model-estimated probability              (float 0-1)
        ``liquidity_usd`` — total USD depth in the orderbook         (float)

    Optional fields forwarded verbatim into ``SignalResult.extra``:
        ``side``  — if omitted, "YES" is inferred when p_model > 0.5 else "NO"
        any other key

    Args:
        markets:              Iterable of market context dicts.
        bankroll:             Current account balance in USD.
        edge_threshold:       Override for minimum edge (env: SIGNAL_EDGE_THRESHOLD).
        min_liquidity_usd:    Override for minimum liquidity (env: SIGNAL_MIN_LIQUIDITY_USD).
        kelly_fraction:       Override for Kelly multiplier (env: SIGNAL_KELLY_FRACTION).
        max_position_fraction: Override for max position size (env: SIGNAL_MAX_POSITION_PCT).

    Returns:
        List of :class:`SignalResult` instances, one per qualifying market.
    """
    _et = edge_threshold if edge_threshold is not None else _env_float(
        "SIGNAL_EDGE_THRESHOLD", _EDGE_THRESHOLD
    )
    _ml = min_liquidity_usd if min_liquidity_usd is not None else _env_float(
        "SIGNAL_MIN_LIQUIDITY_USD", _MIN_LIQUIDITY_USD
    )
    _kf = kelly_fraction if kelly_fraction is not None else _env_float(
        "SIGNAL_KELLY_FRACTION", _KELLY_FRACTION
    )
    _mp = max_position_fraction if max_position_fraction is not None else _env_float(
        "SIGNAL_MAX_POSITION_PCT", _MAX_POSITION_FRACTION
    )

    signals: list[SignalResult] = []

    for market in markets:
        market_id: str = str(market.get("market_id", ""))
        p_market: float = float(market.get("p_market", 0.0))
        p_model: float = float(market.get("p_model", 0.0))
        liquidity_usd: float = float(market.get("liquidity_usd", 0.0))

        # ── 1. Edge calculation ───────────────────────────────────────────────
        edge: float = p_model - p_market

        if edge <= 0:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="non_positive_edge",
                edge=round(edge, 4),
            )
            continue

        # ── 2. EV calculation ─────────────────────────────────────────────────
        # b = decimal odds = (1 / p_market) - 1  (profit per $1 staked)
        if p_market <= 0:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="invalid_p_market",
                p_market=p_market,
            )
            continue

        b: float = (1.0 / p_market) - 1.0
        q: float = 1.0 - p_model
        ev: float = p_model * b - q

        log.info(
            "signal_generated",
            market_id=market_id,
            edge=round(edge, 4),
            ev=round(ev, 4),
            p_model=round(p_model, 4),
            p_market=round(p_market, 4),
        )

        # ── 3. Signal filter ──────────────────────────────────────────────────
        if edge <= _et:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="edge_below_threshold",
                edge=round(edge, 4),
                threshold=round(_et, 4),
            )
            continue

        if liquidity_usd <= _ml:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="insufficient_liquidity",
                liquidity_usd=round(liquidity_usd, 2),
                min_required=round(_ml, 2),
            )
            continue

        # ── 4. Position sizing — fractional Kelly ─────────────────────────────
        kelly_f: float = (p_model * b - q) / b if b > 0 else 0.0
        kelly_f = max(kelly_f, 0.0)  # clamp to non-negative

        raw_size: float = bankroll * _kf * kelly_f
        max_size: float = bankroll * _mp
        size_usd: float = min(raw_size, max_size)

        if size_usd <= 0:
            log.info(
                "trade_skipped",
                market_id=market_id,
                reason="zero_size",
                kelly_f=round(kelly_f, 4),
            )
            continue

        # ── 5. Determine side ─────────────────────────────────────────────────
        side: str = str(market.get("side", "YES" if p_model > 0.5 else "NO"))

        extra: dict[str, Any] = {
            k: v
            for k, v in market.items()
            if k not in {"market_id", "p_market", "p_model", "liquidity_usd", "side"}
        }

        signal = SignalResult(
            signal_id=uuid.uuid4().hex[:12],
            market_id=market_id,
            side=side,
            p_market=round(p_market, 6),
            p_model=round(p_model, 6),
            edge=round(edge, 6),
            ev=round(ev, 6),
            kelly_f=round(kelly_f, 6),
            size_usd=round(size_usd, 4),
            liquidity_usd=round(liquidity_usd, 2),
            extra=extra,
        )
        signals.append(signal)

    return signals
