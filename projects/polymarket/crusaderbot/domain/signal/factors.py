"""SMART STRIKE factor vector — the 7-factor scorable surface + labeled dataset.

WARP-72 Phase 1 (WARP•R00T, SHADOW-only). The audit (WARP-71) found that of the 7
spec factors only TTL is load-bearing: momentum is unmeasured, volatility (sigma)
feeds only the dead-end oracle advisory, and oracle is producer-only. You cannot
score factors that aren't measured — so Phase 1 builds + EXPOSES every factor as a
single, clean, scorable surface and emits it as a labeled-dataset record for the
Phase-2 scorer.

This module NEVER selects, sizes, gates, or blocks a trade. It assembles a
read-only ``FactorVector`` from values the strategy already computed, plus the new
momentum signal, the now-exposed volatility sigma, and the realized open->close
outcome label. It is emitted (structured log + candidate/position metadata) for
EVERY evaluated candle — traded or not — decoupled from execution, exactly like
the oracle advisory observation.

The 7 factors (WARP-71 spec):
    1. momentum   — rolling repricing velocity (NEW; domain/signal/momentum.py)
    2. volatility — per-asset sigma (was oracle-only; now exposed)
    3. liquidity  — CLOB bid/ask depth in USDC
    4. spread     — complete-set cost (yes_ask + no_ask)
    5. depth      — order-book depth in USDC (same source as liquidity, exposed)
    6. ttl        — seconds to candle close
    7. oracle     — advisory fair-value edge (kept as-is; advisory)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import structlog

log = structlog.get_logger(__name__)

# Structured-log event name for the labeled-dataset stream (the Phase-2 source).
FACTOR_VECTOR_EVENT: str = "factor_vector"

# Outcome labels.
OUTCOME_UP: str = "UP"
OUTCOME_DOWN: str = "DOWN"
OUTCOME_FLAT: str = "FLAT"


def realized_candle_outcome(
    open_price: Optional[float],
    ref_price: Optional[float],
    *,
    flat_eps: float = 0.0,
) -> tuple[Optional[str], Optional[float]]:
    """Realized direction + signed return from candle-open to a reference price.

    ``open_price`` is the candle-open underlying (price-to-beat); ``ref_price`` is
    the underlying at observation (near the close window this is the de-facto
    settlement on the same Chainlink source the market resolves against). Returns
    ``(label, delta_fraction)`` or ``(None, None)`` when not computable. ``label``
    is UP / DOWN / FLAT (within ``flat_eps`` fractional move). Pure / fail-soft.
    """
    try:
        if open_price is None or ref_price is None:
            return (None, None)
        o = float(open_price)
        r = float(ref_price)
        if o <= 0.0:
            return (None, None)
        delta = (r - o) / o
        if abs(delta) <= flat_eps:
            return (OUTCOME_FLAT, delta)
        return (OUTCOME_UP if delta > 0.0 else OUTCOME_DOWN, delta)
    except (TypeError, ValueError):
        return (None, None)


@dataclass(frozen=True)
class FactorVector:
    """The full 7-factor scorable surface + label for one evaluated candle.

    Every field is optional/fail-soft: an unmeasured factor stays ``None`` rather
    than a fabricated zero, so the Phase-2 scorer can distinguish "no signal" from
    "zero signal". This object is advisory telemetry only.
    """

    # --- identity / context -------------------------------------------------
    market_id: str
    condition_id: str
    slug: str
    asset: Optional[str]
    timeframe: Optional[str]
    evaluated_rule: Optional[str]          # which rule's scan produced this read

    # --- the 7 factors ------------------------------------------------------
    momentum: Optional[float]              # 1. signed repricing velocity (px/s)
    momentum_delta: Optional[float]
    momentum_span_sec: Optional[float]
    momentum_samples: Optional[int]
    volatility_sigma: Optional[float]      # 2. per-asset sigma (now exposed)
    liquidity_usdc: Optional[float]        # 3. CLOB depth in USDC
    spread: Optional[float]                # 4. complete-set cost yes_ask+no_ask
    orderbook_depth_usdc: Optional[float]  # 5. order-book depth in USDC
    ttl_sec: Optional[float]               # 6. seconds to candle close
    oracle_edge: Optional[float]           # 7. best advisory fair-value edge
    oracle_edge_status: Optional[str]
    oracle_would_pass: Optional[bool]
    oracle_delta: Optional[float]

    # --- candidate shape (context for the scorer) ---------------------------
    fav_side: Optional[str]
    entry_side: Optional[str]
    fav_price: Optional[float]
    entry_price: Optional[float]
    ask_diff: Optional[float]
    complete_set_edge: Optional[float]
    underdog_mode: Optional[bool]

    # --- realized outcome label (open -> close) -----------------------------
    realized_outcome: Optional[str]        # UP / DOWN / FLAT / None
    realized_delta: Optional[float]        # signed fractional move
    outcome_source: Optional[str]          # how the label was resolved
    outcome_observed_rem_sec: Optional[float]  # secs-to-close when label taken
    candle_open_epoch: Optional[float]
    candle_close_epoch: Optional[float]

    # --- router selection (stamped post-dedup; advisory, selection unchanged)
    router_selected_rule: Optional[str] = None
    selected_by_router: bool = False

    def to_metadata(self) -> dict[str, Any]:
        """Flatten to ``factor_*``-prefixed candidate/position metadata keys.

        Uses a shallow ``__dict__`` copy: ``FactorVector`` is a flat dataclass of
        primitives, so the recursive ``dataclasses.asdict`` (a deep copy) is pure
        overhead on this hot per-candle path.
        """
        return {f"factor_{k}": v for k, v in self.__dict__.items()}

    def emit(self, *, extra: Optional[Mapping[str, Any]] = None) -> None:
        """Emit the labeled-dataset record as a structured log (fail-soft)."""
        try:
            payload = dict(self.__dict__)
            if extra:
                payload.update(dict(extra))
            log.info(FACTOR_VECTOR_EVENT, **payload)
        except Exception as exc:  # telemetry must never break a scan
            log.debug("factor_vector emit failed (telemetry, non-blocking)", err=str(exc))


def mark_router_selection(metadata: dict[str, Any], rule: Optional[str]) -> None:
    """Stamp the router-selected rule onto a candidate's factor metadata.

    Advisory only — records WHICH rule the precedence router picked for this
    market so the labeled dataset distinguishes the chosen candidate from the
    also-evaluated alternatives. Does NOT change selection.
    """
    if not isinstance(metadata, dict):
        return
    metadata["factor_router_selected_rule"] = rule
    metadata["factor_selected_by_router"] = True


__all__ = [
    "FactorVector",
    "FACTOR_VECTOR_EVENT",
    "OUTCOME_UP",
    "OUTCOME_DOWN",
    "OUTCOME_FLAT",
    "realized_candle_outcome",
    "mark_router_selection",
]
