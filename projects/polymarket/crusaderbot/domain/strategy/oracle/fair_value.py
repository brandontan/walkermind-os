"""Pure fair-value / edge calculator for Chainlink-resolved crypto candle markets.

WARP-61 Chunk 2 (WARP-63). No I/O -- no network, no DB, no strategy import.
Every function here is a deterministic, fully unit-testable pure function so the
candle edge engine can be validated in isolation before any runtime wiring.

Multi-asset: BTC / ETH / SOL Up/Down candle markets each resolve on their own
Chainlink data stream, and ``sigma`` is PER ASSET (SOL > ETH > BTC realized
vol). The math functions take a scalar ``sigma`` so they stay asset-agnostic;
:func:`sigma_for_asset` resolves the per-asset value from a caller-supplied map
(default :data:`DEFAULT_SIGMA_PER_SQRT_SEC`).

Model
-----
The candle markets resolve on the asset's Chainlink data stream against a
per-candle "Price to Beat" (the candle open). Treating the asset return over the
remaining candle window as a zero-drift Gaussian::

    delta     = (oracle_now - price_to_beat) / price_to_beat       # signed return
    time_left = resolution_ts - now                                # seconds
    sigma     = asset realized vol per sqrt(second)                # PER ASSET
    z         = delta / (sigma * sqrt(time_left))
    fair_up   = Phi(z)                                             # P(close Up)
    edge_up   = fair_up        - best_ask_up
    edge_down = (1 - fair_up)  - best_ask_down

Time-convergence is the alpha: as ``time_left -> 0`` the standard error
``sigma * sqrt(time_left) -> 0`` so ``z`` diverges and ``fair_up -> 0 or 1``,
while the token ask price lags. That gap is the tradeable edge.

The normal CDF uses ``math.erf`` (stdlib) so there is no scipy/numpy dependency
and no chance of an unbounded value: ``erf`` saturates cleanly at +/-1.
"""
from __future__ import annotations

import math
from typing import Mapping, NamedTuple, Optional

# Polymarket CLOB minimum price increment. A token price can never be quoted
# below this, so a missing / empty orderbook side is floored here rather than
# propagated as ``None`` or ``0`` -- this keeps the edge math finite and is the
# documented safe fallback for an absent best-ask.
CLOB_MIN_TICK: float = 0.01

# Seconds in a 365.25-day year -- used to translate an annualized realized-vol
# figure into the per-sqrt-second ``sigma`` the model consumes.
_SECONDS_PER_YEAR: float = 365.25 * 24.0 * 60.0 * 60.0  # 31_557_600.0

# Per-asset realized-vol scale (``sigma`` per sqrt-second). sigma is PER ASSET
# because realized vol differs materially across these candle markets --
# SOL > ETH > BTC -- so a single shared sigma would misprice fair value on the
# higher-vol assets (a larger sigma pulls ``fair_up`` toward 0.5). Each default
# is ``annualized_vol / sqrt(_SECONDS_PER_YEAR)``; cross-check with
# :func:`annual_vol_to_sigma`:
#   btc 0.00010 ~= 56%  annualized (0.00010 * sqrt(31_557_600) ~= 0.562)
#   eth 0.00013 ~= 73%  annualized (ETH realized vol historically above BTC)
#   sol 0.00020 ~= 112% annualized (SOL the most volatile of the three)
# These mirror the Settings ``oracle_sigma_per_sqrt_sec`` env-tunable defaults;
# the calculator stays pure -- callers pass a map in, this is only the fallback.
DEFAULT_SIGMA_PER_SQRT_SEC: dict[str, float] = {
    "btc": 0.00010,
    "eth": 0.00013,
    "sol": 0.00020,
}


def _require_finite(name: str, value: float) -> float:
    """Reject NaN / inf inputs explicitly -- no silent propagation of garbage."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def normal_cdf(z: float) -> float:
    """Standard normal CDF Phi(z) in [0, 1], via the error function.

    Phi(z) = 0.5 * (1 + erf(z / sqrt(2))). ``math.erf`` saturates at +/-1 for
    large magnitudes, so extreme ``z`` returns exactly 0.0 or 1.0 without
    overflow.
    """
    _require_finite("z", z)
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def sigma_for_asset(
    asset: str,
    sigma_map: Optional[Mapping[str, float]] = None,
) -> float:
    """Resolve the per-sqrt-second ``sigma`` for an asset symbol (pure lookup).

    The calculator never reads Settings / network itself: the strategy layer
    (Chunk 3) passes the Settings-derived ``oracle_sigma_per_sqrt_sec`` map in.
    When ``sigma_map`` is omitted, :data:`DEFAULT_SIGMA_PER_SQRT_SEC` is used.

    ``asset`` is case-insensitive (``"BTC"`` == ``"btc"``). An unknown symbol or
    a non-finite calibrated value raises ``ValueError`` -- no silent default to
    a wrong-vol sigma, which would misprice fair value.
    """
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError(f"asset must be a non-empty symbol, got {asset!r}")
    key = asset.strip().lower()
    table = DEFAULT_SIGMA_PER_SQRT_SEC if sigma_map is None else sigma_map
    if key not in table:
        raise ValueError(
            f"no sigma calibrated for asset {asset!r}; known: {sorted(table)}"
        )
    return _require_finite(f"sigma[{key}]", float(table[key]))


def compute_delta(oracle_now: float, price_to_beat: float) -> float:
    """Signed candle return ``(oracle_now - price_to_beat) / price_to_beat``.

    ``oracle_now`` is the current oracle reading for the asset (BTC/ETH/SOL
    Chainlink data stream); ``price_to_beat`` is the candle-open reference and
    must be strictly positive (an asset price), otherwise the return is
    undefined.
    """
    _require_finite("oracle_now", oracle_now)
    _require_finite("price_to_beat", price_to_beat)
    if price_to_beat <= 0.0:
        raise ValueError(f"price_to_beat must be > 0, got {price_to_beat!r}")
    return (oracle_now - price_to_beat) / price_to_beat


def compute_fair_value(delta: float, time_left: float, sigma: float) -> float:
    """P(candle closes Up) = Phi(delta / (sigma * sqrt(time_left))), in [0, 1].

    Edge cases (deterministic, no exceptions for the degenerate regimes):

    * ``delta == 0``            -> 0.5 (no information either way).
    * ``time_left <= 0`` or
      ``sigma <= 0``            -> degenerate zero-variance limit: 1.0 if
                                   ``delta > 0``, 0.0 if ``delta < 0``, else 0.5.
                                   This is the ``time_left -> 0`` convergence
                                   limit made exact at the boundary.

    Raises ``ValueError`` only on non-finite (NaN / inf) inputs.
    """
    _require_finite("delta", delta)
    _require_finite("time_left", time_left)
    _require_finite("sigma", sigma)

    # No directional information -> coin flip, regardless of vol / time.
    if delta == 0.0:
        return 0.5

    # Zero-variance limit (no time left or no vol): outcome is already decided
    # by the sign of the current deviation. Phi(+/-inf) = 1 / 0.
    if time_left <= 0.0 or sigma <= 0.0:
        return 1.0 if delta > 0.0 else 0.0

    std = sigma * math.sqrt(time_left)
    # Numerical-underflow guard: with sigma and time_left both tiny but positive,
    # ``std`` can round to 0.0, which would make ``delta / std`` raise
    # ZeroDivisionError. That regime is the same zero-variance limit as the
    # ``time_left <= 0`` / ``sigma <= 0`` branch above -> outcome decided by the
    # sign of delta (delta == 0 already returned 0.5 earlier).
    if std <= 0.0:
        return 1.0 if delta > 0.0 else 0.0

    z = delta / std
    return normal_cdf(z)


class EdgeResult(NamedTuple):
    """Edge of each side, plus the (normalized) asks the edge was computed from.

    ``edge_*`` is ``fair_probability - ask`` for that side: positive means the
    model thinks the side is underpriced (a buy edge). Asks are returned after
    normalization (missing / out-of-range floored to the CLOB tick) so callers
    can log exactly what price the edge reflects.
    """

    edge_up: float
    edge_down: float
    ask_up: float
    ask_down: float


def _normalize_ask(ask: Optional[float]) -> float:
    """Clamp a best-ask into the tradeable ``[CLOB_MIN_TICK, 1.0]`` band.

    A missing (``None``), non-finite, or non-positive ask is treated as the
    ``0.01`` CLOB minimum tick -- the documented safe fallback so a missing
    orderbook side never produces a ``None``/``NaN`` edge. A quote above 1.0 is
    clamped to 1.0 (a binary token cannot be worth more than full settlement).
    """
    if ask is None or not math.isfinite(ask) or ask <= 0.0:
        return CLOB_MIN_TICK
    if ask < CLOB_MIN_TICK:
        return CLOB_MIN_TICK
    if ask > 1.0:
        return 1.0
    return float(ask)


def compute_edge(
    fair_up: float,
    ask_up: Optional[float],
    ask_down: Optional[float],
) -> EdgeResult:
    """Edge for the Up and Down sides given the model ``fair_up`` and best asks.

    ``edge_up   = fair_up        - ask_up``
    ``edge_down = (1 - fair_up)  - ask_down``

    Asks are normalized via :func:`_normalize_ask` (missing -> 0.01 tick).
    ``fair_up`` must be a finite probability in ``[0, 1]``.
    """
    _require_finite("fair_up", fair_up)
    if not (0.0 <= fair_up <= 1.0):
        raise ValueError(f"fair_up must be in [0, 1], got {fair_up!r}")

    a_up = _normalize_ask(ask_up)
    a_down = _normalize_ask(ask_down)
    edge_up = fair_up - a_up
    edge_down = (1.0 - fair_up) - a_down
    return EdgeResult(edge_up=edge_up, edge_down=edge_down, ask_up=a_up, ask_down=a_down)


def annual_vol_to_sigma(annual_vol: float) -> float:
    """Convert an annualized realized vol into ``sigma`` per sqrt(second).

    ``sigma = annual_vol / sqrt(seconds_per_year)``. Helper for documenting and
    calibrating the configured ``ORACLE_BTC_SIGMA_PER_SQRT_SEC`` default against
    a BTC realized-vol figure (e.g. 0.56 annualized ~= 0.00010 per sqrt-sec).
    """
    _require_finite("annual_vol", annual_vol)
    if annual_vol < 0.0:
        raise ValueError(f"annual_vol must be >= 0, got {annual_vol!r}")
    return annual_vol / math.sqrt(_SECONDS_PER_YEAR)
