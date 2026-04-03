"""core.signal.signal_engine — Edge-based signal generation pipeline.

For each market in the supplied list this module:

1. Reads ``p_market`` (the current market-implied probability) and
   ``p_model``   (the model's estimated probability).
   ``p_model`` is either supplied in the market dict or computed by the
   optional :class:`~core.signal.alpha_model.ProbabilisticAlphaModel`.
2. Computes ``edge = p_model - p_market``.
3. Skips the market if ``edge <= 0`` (no positive edge).
4. Computes Expected Value: ``EV = p_model * b - (1 - p_model)``
   where ``b`` (decimal odds) is derived from the market price:
   ``b = (1 / p_market) - 1``.
5. Applies the signal filter — only continues when:
   - ``edge > EDGE_THRESHOLD``   (default 0.005, i.e. 0.5 %)
   - ``liquidity_usd > MIN_LIQUIDITY_USD``   (default $10,000)
   - ``confidence_score > MIN_CONFIDENCE``   (default 0.1)
     where ``confidence_score = edge / volatility`` and volatility is
     estimated from the bid-ask spread (or alpha model if provided).
6. Sizes the position using fractional Kelly:
   ``kelly_f = (p * b - q) / b``  (where q = 1 - p_model)
   ``size    = bankroll * KELLY_FRACTION * kelly_f``
   clamped to at most ``MAX_POSITION_FRACTION * bankroll``.
7. Emits a ``log.info("signal_generated", ...)`` event and appends the
   :class:`SignalResult` to the output list.

Environment variables (all optional):
    SIGNAL_EDGE_THRESHOLD     — minimum edge to generate signal (default 0.005)
    SIGNAL_MIN_LIQUIDITY_USD  — minimum liquidity required   (default 10000)
    SIGNAL_KELLY_FRACTION     — fractional-Kelly multiplier  (default 0.25)
    SIGNAL_MAX_POSITION_PCT   — max position as fraction of bankroll (default 0.10)
    SIGNAL_MIN_CONFIDENCE     — minimum confidence score S=edge/vol  (default 0.1)
    FORCE_SIGNAL_MODE         — when "true", bypasses all filters and generates up
                                to FORCE_SIGNAL_TOP_N signals per call using a
                                simplified side rule: p_market < 0.5 → YES else NO.
                                Position size is capped at 1 % of bankroll.
    FORCE_SIGNAL_TOP_N        — max number of forced signals per call (default 1)

Usage::

    from core.signal import generate_signals

    signals = await generate_signals(markets, bankroll=5000.0)
    for s in signals:
        print(s.market_id, s.edge, s.size_usd)
"""
from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .alpha_model import ProbabilisticAlphaModel

log = structlog.get_logger()

# ── Configuration defaults ─────────────────────────────────────────────────────

_EDGE_THRESHOLD: float = 0.005         # 0.5 % base minimum edge
_VOLATILITY_THRESHOLD_SCALE: float = 0.5  # dynamic threshold = base + vol * scale
_MIN_LIQUIDITY_USD: float = 10_000.0   # $10,000 minimum market depth
_KELLY_FRACTION: float = 0.25          # fractional Kelly multiplier
_MAX_POSITION_FRACTION: float = 0.10   # max 10 % of bankroll per trade
_MIN_CONFIDENCE: float = 0.1           # minimum S = edge / volatility
_FORCE_SIGNAL_TOP_N: int = 1           # default markets to force-signal per call
_MIN_FORCE_MODE_EDGE: float = 0.01     # minimum edge injected in force mode

# ── Strategy adjustment constants ──────────────────────────────────────────────

_MEAN_REVERSION_WEIGHT: float = 0.1    # fraction of 0.5 blended into p_model


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _spread_volatility(market: dict[str, Any], p_market: float) -> float:
    """Estimate volatility from bid-ask spread.

    Falls back to a small default when bid/ask are not in the market dict.

    Args:
        market: Market context dict.
        p_market: Current market-implied probability (used as fallback price).

    Returns:
        Spread value, at least ``1e-4``.
    """
    bid = float(market.get("bid", p_market))
    ask = float(market.get("ask", p_market))
    spread = ask - bid
    return max(spread, 1e-4)


def _dynamic_edge_threshold(base: float, volatility: float, scale: float) -> float:
    """Compute a dynamic edge threshold adjusted for current market volatility.

    In volatile markets the threshold rises, reducing overtrading noise.
    In stable markets the threshold stays close to the base.

    Args:
        base: Base minimum edge (e.g. 0.005).
        volatility: Current market volatility estimate.
        scale: Volatility multiplier (e.g. 0.5).

    Returns:
        Adjusted edge threshold: ``base + volatility * scale``.
    """
    return base + volatility * scale


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
    force_mode: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# ── Core logic ─────────────────────────────────────────────────────────────────


async def generate_signals(
    markets: Sequence[dict[str, Any]],
    bankroll: float = 1_000.0,
    edge_threshold: float | None = None,
    min_liquidity_usd: float | None = None,
    kelly_fraction: float | None = None,
    max_position_fraction: float | None = None,
    min_confidence: float | None = None,
    alpha_model: "Optional[ProbabilisticAlphaModel]" = None,
    force_signal_mode: bool | None = None,
    strategy_state: "Optional[dict[str, bool]]" = None,
) -> list[SignalResult]:
    """Evaluate a list of markets and return signals with positive edge.

    Each market dict is expected to contain at minimum:
        ``market_id``     — Polymarket condition ID (str)
        ``p_market``      — current market price / implied probability (float 0-1)
        ``p_model``       — model-estimated probability (float 0-1); used when
                            no *alpha_model* is provided.
        ``liquidity_usd`` — total USD depth in the orderbook         (float)

    Optional fields used for confidence scoring:
        ``bid`` / ``ask`` — bid and ask prices for spread-based volatility.
        any other key is forwarded verbatim into ``SignalResult.extra``.

    When *alpha_model* is supplied it overrides the ``p_model`` key and also
    provides a model-computed volatility for the confidence score.  The caller
    is responsible for calling ``alpha_model.record_tick`` on each price update
    before invoking this function.

    Args:
        markets:              Iterable of market context dicts.
        bankroll:             Current account balance in USD.
        edge_threshold:       Override for minimum edge (env: SIGNAL_EDGE_THRESHOLD).
        min_liquidity_usd:    Override for minimum liquidity (env: SIGNAL_MIN_LIQUIDITY_USD).
        kelly_fraction:       Override for Kelly multiplier (env: SIGNAL_KELLY_FRACTION).
        max_position_fraction: Override for max position size (env: SIGNAL_MAX_POSITION_PCT).
        min_confidence:       Override for minimum confidence score S=edge/vol
                              (env: SIGNAL_MIN_CONFIDENCE).  Set to 0.0 to disable.
        alpha_model:          Optional :class:`~core.signal.alpha_model.ProbabilisticAlphaModel`
                              for real p_model and volatility computation.
        force_signal_mode:    When True, bypasses all filters and emits up to
                              ``FORCE_SIGNAL_TOP_N`` signals (env: FORCE_SIGNAL_MODE).
                              Sizes each position at exactly 1 % of bankroll.
        strategy_state:       Optional dict mapping strategy name → enabled bool.
                              When provided only active strategies contribute to
                              p_model.  If None all strategies are treated as active.

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
    _mc = min_confidence if min_confidence is not None else _env_float(
        "SIGNAL_MIN_CONFIDENCE", _MIN_CONFIDENCE
    )
    _force = force_signal_mode if force_signal_mode is not None else _env_bool(
        "FORCE_SIGNAL_MODE"
    )

    # ── FORCE SIGNAL MODE ─────────────────────────────────────────────────────
    # When enabled: bypass all filters, generate signals for top N markets using
    # a simple direction rule, and cap size at 1 % of bankroll.
    if _force:
        _top_n = _env_int("FORCE_SIGNAL_TOP_N", _FORCE_SIGNAL_TOP_N)
        _force_size = bankroll * 0.01  # 1 % bankroll cap

        log.info(
            "force_signal_mode_active",
            top_n=_top_n,
            bankroll=bankroll,
            force_size_usd=round(_force_size, 4),
        )

        forced: list[SignalResult] = []
        for market in list(markets)[:_top_n]:
            market_id: str = str(market.get("market_id", ""))
            p_market: float = float(market.get("p_market", 0.0))
            liquidity_usd: float = float(market.get("liquidity_usd", 0.0))

            if alpha_model is not None:
                p_model, volatility = alpha_model.compute_p_model(
                    market_id=market_id,
                    p_market=p_market,
                    liquidity_usd=liquidity_usd,
                    force_mode=True,
                )
            else:
                p_model = float(market.get("p_model", p_market))
                volatility = _spread_volatility(market, p_market)

            edge: float = p_model - p_market

            # ── Force mode: guarantee non-zero edge ───────────────────────────
            # When no alpha model is available and p_model == p_market, inject
            # a minimal edge so the execution guard allows the trade.
            if edge <= 0:
                edge = _MIN_FORCE_MODE_EDGE
                p_model = max(0.01, min(0.99, p_market + edge))
                log.info(
                    "alpha_injected",
                    market_id=market_id,
                    injected_edge=_MIN_FORCE_MODE_EDGE,
                    p_market=round(p_market, 4),
                    p_model=round(p_model, 4),
                    force_mode=True,
                )
            confidence_score: float = edge / volatility if volatility > 0 else 0.0

            # Simple forced side rule
            side: str = "YES" if p_market < 0.5 else "NO"

            # Compute EV even in force mode (may be negative)
            b: float = (1.0 / p_market - 1.0) if p_market > 0 else 0.0
            q: float = 1.0 - p_model
            ev: float = (p_model * b - q) if b > 0 else 0.0

            kelly_f: float = max((p_model * b - q) / b, 0.0) if b > 0 else 0.0

            log.info(
                "signal_debug",
                market_id=market_id,
                p_market=round(p_market, 4),
                p_model=round(p_model, 4),
                edge=round(edge, 4),
                volatility=round(volatility, 6),
                S=round(confidence_score, 4),
                force_mode=True,
            )

            log.info(
                "signal_generated",
                market_id=market_id,
                edge=round(edge, 4),
                ev=round(ev, 4),
                p_model=round(p_model, 4),
                p_market=round(p_market, 4),
                side=side,
                size_usd=round(_force_size, 4),
                force_mode=True,
            )

            extra: dict[str, Any] = {
                k: v
                for k, v in market.items()
                if k not in {"market_id", "p_market", "p_model", "liquidity_usd", "side"}
            }

            forced.append(SignalResult(
                signal_id=uuid.uuid4().hex[:12],
                market_id=market_id,
                side=side,
                p_market=round(p_market, 6),
                p_model=round(p_model, 6),
                edge=round(edge, 6),
                ev=round(ev, 6),
                kelly_f=round(kelly_f, 6),
                size_usd=round(_force_size, 4),
                liquidity_usd=round(liquidity_usd, 2),
                force_mode=True,
                extra=extra,
            ))

        return forced

    signals: list[SignalResult] = []

    for market in markets:
        market_id: str = str(market.get("market_id", ""))
        p_market: float = float(market.get("p_market", 0.0))
        liquidity_usd: float = float(market.get("liquidity_usd", 0.0))

        # ── p_model and volatility ────────────────────────────────────────────
        if alpha_model is not None:
            # Stateful model computes p_model from deviation + momentum + liquidity
            p_model, volatility = alpha_model.compute_p_model(
                market_id=market_id,
                p_market=p_market,
                liquidity_usd=liquidity_usd,
            )
        else:
            # Use the caller-supplied p_model from the market dict
            p_model = float(market.get("p_model", p_market))
            # Volatility estimated from bid-ask spread
            volatility = _spread_volatility(market, p_market)

        # ── Strategy-state p_model adjustments ───────────────────────────────
        # Apply each active strategy component; log which strategies contributed.
        _use_ev_momentum: bool = True
        _use_mean_reversion: bool = True
        _use_liquidity_edge: bool = True
        if strategy_state is not None:
            _use_ev_momentum = bool(strategy_state.get("ev_momentum", True))
            _use_mean_reversion = bool(strategy_state.get("mean_reversion", True))
            _use_liquidity_edge = bool(strategy_state.get("liquidity_edge", True))

            # ev_momentum disabled: remove momentum-derived edge (set p_model = p_market)
            if not _use_ev_momentum:
                p_model = p_market

            # mean_reversion active: pull p_model slightly toward 0.5
            if _use_mean_reversion and p_model != p_market:
                p_model = p_model * (1.0 - _MEAN_REVERSION_WEIGHT) + 0.5 * _MEAN_REVERSION_WEIGHT

            # liquidity_edge active: scale p_model edge by log-liquidity factor
            if _use_liquidity_edge and liquidity_usd > 0 and p_model != p_market:
                liq_factor: float = min(1.0, math.log1p(liquidity_usd) / math.log1p(_MIN_LIQUIDITY_USD))
                p_model = p_market + (p_model - p_market) * liq_factor

            # Clamp to valid probability range
            p_model = max(0.001, min(0.999, p_model))

            log.info(
                "strategy_used_in_signal",
                market_id=market_id,
                ev_momentum=_use_ev_momentum,
                mean_reversion=_use_mean_reversion,
                liquidity_edge=_use_liquidity_edge,
                p_model_adjusted=round(p_model, 4),
            )

        # ── 1. Edge calculation ───────────────────────────────────────────────
        edge: float = p_model - p_market

        # ── Dynamic edge threshold (base + volatility_adjustment) ─────────────
        _vol_scale = _env_float("SIGNAL_VOL_THRESHOLD_SCALE", _VOLATILITY_THRESHOLD_SCALE)
        effective_threshold: float = _et + volatility * _vol_scale

        # ── Confidence score (computed early for logging) ─────────────────────
        confidence_score: float = edge / volatility if edge > 0 else 0.0

        log.info(
            "signal_debug",
            market_id=market_id,
            p_market=round(p_market, 4),
            p_model=round(p_model, 4),
            edge=round(edge, 4),
            volatility=round(volatility, 6),
            effective_threshold=round(effective_threshold, 6),
            S=round(confidence_score, 4),
        )

        log.info(
            "alpha_debug",
            market_id=market_id,
            p_market=round(p_market, 4),
            p_model=round(p_model, 4),
            edge=round(edge, 4),
            volatility=round(volatility, 6),
            S=round(confidence_score, 4),
        )

        if edge <= 0:
            log.info(
                "signal_skipped",
                market_id=market_id,
                edge=round(edge, 4),
                S=round(confidence_score, 4),
                reason="non_positive_edge",
            )
            continue

        # ── 2. EV calculation ─────────────────────────────────────────────────
        # b = decimal odds = (1 / p_market) - 1  (profit per $1 staked)
        if p_market <= 0:
            log.info(
                "signal_skipped",
                market_id=market_id,
                edge=round(edge, 4),
                S=round(confidence_score, 4),
                reason="invalid_p_market",
            )
            continue

        b: float = (1.0 / p_market) - 1.0
        q: float = 1.0 - p_model
        ev: float = p_model * b - q

        # ── 3. Signal filter (dynamic threshold) ─────────────────────────────
        if edge <= effective_threshold:
            log.info(
                "signal_skipped",
                market_id=market_id,
                edge=round(edge, 4),
                S=round(confidence_score, 4),
                reason="edge_below_threshold",
                threshold=round(effective_threshold, 4),
            )
            continue

        if liquidity_usd <= _ml:
            log.info(
                "signal_skipped",
                market_id=market_id,
                edge=round(edge, 4),
                S=round(confidence_score, 4),
                reason="insufficient_liquidity",
                liquidity_usd=round(liquidity_usd, 2),
                min_required=round(_ml, 2),
            )
            continue

        # ── 4. Confidence score filter (S = edge / volatility) ────────────────
        if confidence_score < _mc:
            log.info(
                "signal_skipped",
                market_id=market_id,
                edge=round(edge, 4),
                S=round(confidence_score, 4),
                reason="confidence_below_threshold",
                min_confidence=round(_mc, 4),
            )
            continue

        log.info(
            "signal_generated",
            market_id=market_id,
            edge=round(edge, 4),
            ev=round(ev, 4),
            p_model=round(p_model, 4),
            p_market=round(p_market, 4),
            confidence_score=round(confidence_score, 4),
        )

        # ── 5. Position sizing — fractional Kelly ─────────────────────────────
        kelly_f: float = (p_model * b - q) / b if b > 0 else 0.0
        kelly_f = max(kelly_f, 0.0)  # clamp to non-negative

        raw_size: float = bankroll * _kf * kelly_f
        max_size: float = bankroll * _mp
        size_usd: float = min(raw_size, max_size)

        if size_usd <= 0:
            log.info(
                "signal_skipped",
                market_id=market_id,
                edge=round(edge, 4),
                S=round(confidence_score, 4),
                reason="zero_size",
                kelly_f=round(kelly_f, 4),
            )
            continue

        # ── 6. Determine side ─────────────────────────────────────────────────
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
