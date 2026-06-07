"""Pre-trade slippage estimator — factor-vector → expected slippage (bps).

WARP-83 Sub-Lane A (research / modeling). This module estimates the EXPECTED
slippage of a prospective entry *before* it is sent, using only fields that
already exist on the ``factor_vectors`` surface (domain/signal/factors.py):

    liquidity_usdc, spread, orderbook_depth_usdc, complete_set_edge,
    entry_price, current_price

It is a distinct concern from ``domain/execution/slippage.py``:

  * ``domain/execution/slippage.py`` enforces *execution-time* guardrails —
    a market-impact ratio gate and a live price-deviation gate. It answers
    "is this order allowed?" with an accept/reject verdict.
  * ``domain/research/slippage_estimator.py`` (this module) *estimates* the
    magnitude of slippage in basis points from a pre-trade factor vector. It
    answers "how much will it cost?" — a continuous prediction feeding research
    / EV modeling, not a runtime gate.

The two compose: the execution guard can keep using its impact ratio, while
research / EV work consumes the bps estimate produced here.

Model shape
-----------
    slippage_bps = spread_cost_bps
                 + impact_coeff * sqrt(stake / orderbook_depth) * 1e4
                 + move_coeff   * abs_price_move_bps

Three additive, deterministic components:

  1. **Spread cost** — half the bid/ask cost crossed on entry. On Polymarket the
     ``spread`` factor is the complete-set cost ``yes_ask + no_ask`` (≈ 1.0 for a
     liquid binary market). The excess over the 1.0 fair complete-set value is the
     round-trip spread; a single-leg taker crosses ~half of it.

  2. **Market impact** — a square-root law in the participation ratio
     ``stake / orderbook_depth``. The square-root (Almgren / Bouchaud
     square-root-impact) law is the empirically robust functional form for
     market impact across asset classes, and the Polymarket order-book
     microstructure study confirms depth-driven, concave impact in prediction
     markets. Square-root (concave) is preferred over linear so that small
     stakes against deep books incur near-zero impact while large stakes against
     thin books are penalized super-linearly in the ratio.

  3. **Adverse price move** — when the live ``current_price`` has already moved
     away from the intended ``entry_price``, that realized drift is an additional
     execution cost; ``move_coeff`` scales how much of it is attributed to
     slippage (vs. genuine repricing).

The function is PURE and DETERMINISTIC: no network, no DB, no async, no clock.
The caller supplies all factor inputs. Division-by-zero (depth → 0) is handled
explicitly: a non-positive / near-zero book is treated as maximally illiquid and
the participation ratio is clamped to a configured ceiling (logged, never
silent).

References
----------
  * J.-P. Bouchaud et al., square-root market-impact law (LLOB / "markets never
    forget"): impact grows ~ sqrt(executed volume / available liquidity).
  * "The Anatomy of a Decentralized Prediction Market: Microstructure Evidence
    from the Polymarket Order Book" (arXiv:2604.24366) — depth concentration and
    concave, depth-driven impact in Polymarket binary markets.
  * Almgren et al. (2005), nonlinear concave (≈ 3/5–square-root) impact in size.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import structlog

log = structlog.get_logger(__name__)

# --- model parameters (calibration baseline, overridable per call) -----------
# Rationale: grounded in the square-root impact literature + observed
# factor_vectors ranges (spread ~ 1.0 complete-set cost; depth 0.5k-110k USDC).

# Impact coefficient on sqrt(participation): a stake equal to the full book
# (ratio = 1.0) contributes ``IMPACT_COEFF_DEFAULT`` * 1.0 * 1e4 bps before the
# sqrt damping. 0.02 -> ~200 bps at full-book participation, a conservative
# prediction-market baseline pending empirical fit.
IMPACT_COEFF_DEFAULT: Final[float] = 0.02

# Fraction of the round-trip spread a single taker leg actually crosses.
SPREAD_CROSS_FRACTION_DEFAULT: Final[float] = 0.5

# Fair complete-set value for a binary market (yes + no = 1.0). The ``spread``
# factor's excess over this is the round-trip spread cost.
COMPLETE_SET_FAIR_VALUE: Final[float] = 1.0

# Attribution of an already-realized adverse price move to slippage.
MOVE_COEFF_DEFAULT: Final[float] = 1.0

# Participation ratio used when the order book is non-positive / near-zero.
# Treated as maximally illiquid (stake >> depth) -> ratio clamped to this ceiling.
ILLIQUID_PARTICIPATION_CEILING: Final[float] = 4.0

# Depth at or below this (USDC) is treated as "no usable book" (guard div-by-0).
MIN_USABLE_DEPTH_USDC: Final[float] = 1.0

_BPS: Final[float] = 1.0e4


@dataclass(frozen=True)
class SlippageEstimate:
    """Decomposed pre-trade slippage estimate, in basis points.

    ``total_bps`` is the sum of the three components. Components are exposed so
    callers / research can attribute cost and audit the estimate.
    """

    total_bps: float
    spread_cost_bps: float
    impact_bps: float
    adverse_move_bps: float
    participation_ratio: float
    illiquid_book: bool


def _participation_ratio(
    stake_usdc: float, orderbook_depth_usdc: float
) -> tuple[float, bool]:
    """Return ``(ratio, illiquid)`` for ``stake / depth`` with an explicit guard.

    A non-positive or near-zero book cannot absorb the stake; rather than divide
    by zero we clamp the ratio to ``ILLIQUID_PARTICIPATION_CEILING`` and flag the
    condition (logged by the caller, never silently swallowed).
    """
    if (
        not math.isfinite(orderbook_depth_usdc)
        or orderbook_depth_usdc <= MIN_USABLE_DEPTH_USDC
    ):
        return (ILLIQUID_PARTICIPATION_CEILING, True)
    if not math.isfinite(stake_usdc) or stake_usdc <= 0.0:
        return (0.0, False)
    ratio = stake_usdc / orderbook_depth_usdc
    return (min(ratio, ILLIQUID_PARTICIPATION_CEILING), False)


def _spread_cost_bps(spread: float, *, cross_fraction: float) -> float:
    """Single-leg taker spread cost in bps from the complete-set ``spread`` factor.

    ``spread`` is ``yes_ask + no_ask``; its excess over the 1.0 fair complete-set
    value is the round-trip spread. A taker crosses ``cross_fraction`` of it.
    Negative excess (sub-fair quoted set) is floored at zero.
    """
    if not math.isfinite(spread):
        return 0.0
    round_trip = max(0.0, spread - COMPLETE_SET_FAIR_VALUE)
    return round_trip * cross_fraction * _BPS


def estimate_slippage_bps(
    *,
    stake_usdc: float,
    orderbook_depth_usdc: float,
    spread: float,
    entry_price: float,
    current_price: float | None = None,
    impact_coeff: float = IMPACT_COEFF_DEFAULT,
    move_coeff: float = MOVE_COEFF_DEFAULT,
    spread_cross_fraction: float = SPREAD_CROSS_FRACTION_DEFAULT,
) -> SlippageEstimate:
    """Estimate expected entry slippage (bps) from pre-trade factor inputs.

    Pure / deterministic — no I/O. All inputs are caller-supplied; on Polymarket
    they map to ``factor_vectors`` fields: ``orderbook_depth_usdc``, ``spread``,
    ``entry_price``, ``current_price``. ``stake_usdc`` is the intended order
    notional (caller-derived; e.g. from sizing).

    Model::

        slippage_bps = spread_cost_bps
                     + impact_coeff * sqrt(stake / depth) * 1e4
                     + move_coeff   * abs_price_move_bps

    Edge handling (no silent failures):
      * ``orderbook_depth_usdc`` <= ``MIN_USABLE_DEPTH_USDC`` -> book treated as
        maximally illiquid: participation clamped to the ceiling, ``illiquid_book``
        flagged and logged at WARNING.
      * Non-finite numeric inputs are coerced to a safe zero contribution rather
        than propagating NaN/inf.
    """
    ratio, illiquid = _participation_ratio(stake_usdc, orderbook_depth_usdc)
    if illiquid:
        log.warning(
            "slippage_estimator illiquid book — participation clamped",
            orderbook_depth_usdc=orderbook_depth_usdc,
            stake_usdc=stake_usdc,
            clamped_ratio=ratio,
        )

    spread_cost_bps = _spread_cost_bps(spread, cross_fraction=spread_cross_fraction)

    impact_bps = impact_coeff * math.sqrt(max(0.0, ratio)) * _BPS

    adverse_move_bps = 0.0
    if (
        current_price is not None
        and math.isfinite(current_price)
        and math.isfinite(entry_price)
        and entry_price > 0.0
    ):
        abs_move_frac = abs(current_price - entry_price) / entry_price
        adverse_move_bps = move_coeff * abs_move_frac * _BPS

    total_bps = spread_cost_bps + impact_bps + adverse_move_bps

    return SlippageEstimate(
        total_bps=total_bps,
        spread_cost_bps=spread_cost_bps,
        impact_bps=impact_bps,
        adverse_move_bps=adverse_move_bps,
        participation_ratio=ratio,
        illiquid_book=illiquid,
    )


__all__ = [
    "SlippageEstimate",
    "estimate_slippage_bps",
    "IMPACT_COEFF_DEFAULT",
    "MOVE_COEFF_DEFAULT",
    "SPREAD_CROSS_FRACTION_DEFAULT",
    "ILLIQUID_PARTICIPATION_CEILING",
    "MIN_USABLE_DEPTH_USDC",
]
