"""Tiered LIVE-cutover slippage gate (WARP-83 Sub-Lane C -> WARP-87).

Wires the locked Sub-Lane C threshold proposal
(``reports/forge/cutover-slippage-thresholds.md``, PR #1691) into the RISK stage
as a tiered *slippage-of-edge* gate plus per-cell LIVE size caps.

Pipeline position (CLAUDE.md SYSTEM PIPELINE — LOCKED):

    DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING

The slippage gate lives in the RISK stage **only** — the STRATEGY stage never
owns it. It is consumed by ``domain/risk/gate.py:evaluate`` at the slippage step,
AFTER the market-impact ratio guard (step 14) and ONLY for a trade the gate is
about to route LIVE. Paper sizing (~$7) leaves the size-dependent market-impact
term dormant and paper accrual still feeds the EV/cutover analysis, so paper
trades are intentionally left untouched; the proposal is explicitly the LIVE
cutover instrument.

Tiers (locked, owner pick WARP-87) — slippage(bps) / gross edge(bps):

    GREEN  <= 15%        -> pass through
    WATCH  15% .. 30%    -> log + alert, pass through
    HALT   > 30%         -> reject candidate (reason ``slippage_halt``)

Initial LIVE per-trade size caps (locked, owner pick WARP-87):

    btc/5m  $500
    eth/5m  $100
    sol/5m  $100   (conservative initial cap — pending live-fill observation)

PURE / DETERMINISTIC — no DB, no async, no network, no clock. Every input is
caller-supplied from the ``GateContext`` already in hand. This is a hard
requirement, not a preference: PR #1694 placed a per-candidate DB read in the
gate hot path, exhausted the asyncpg pool, and wedged the event loop
(see ``docs/rca/2026-06-07-gate-hotpath-incident.md``). The slippage gate must
NEVER read the DB in the per-candidate path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# --- Locked Sub-Lane C tiers (PR #1691; owner pick WARP-87) ------------------
# slippage(bps) / gross edge(bps), per candidate at the planned LIVE notional.
# Boundaries are inclusive on the lower tier: exactly 15% is GREEN, exactly 30%
# is WATCH; strictly above 30% is HALT (proposal "GREEN <=15 / WATCH 15-30 /
# HALT >30").
SLIPPAGE_GREEN_MAX_FRAC: float = 0.15
SLIPPAGE_WATCH_MAX_FRAC: float = 0.30

# Initial LIVE per-trade size caps (USDC), keyed by trading cell
# ``"{asset}/{timeframe}"`` (lower-case). Owner-locked (WARP-87): keep both
# target cutover cells strictly GREEN at launch. eth/5m is the binding
# constraint (shallower book, lower edge); btc/5m stays GREEN to large size.
# Re-tuned after the first LIVE week.
#
# WARP-87 follow-up (smart-strike-cell-cap-binding): sol/5m added for the
# CMD-approved LIVE v1 cell set (BTC + ETH + SOL, 5m). sol/5m=$100 is a
# conservative initial cap pending live-fill observation — flagged for final
# CMD confirm; re-tune alongside btc/eth after the first LIVE week.
LIVE_SIZE_CAPS_USDC: dict[str, float] = {
    "btc/5m": 500.0,
    "eth/5m": 100.0,
    "sol/5m": 100.0,
}


class SlippageTier(str, Enum):
    """Slippage-of-edge tier. ``str`` mixin so the value logs/serialises cleanly."""

    GREEN = "green"
    WATCH = "watch"
    HALT = "halt"


@dataclass(frozen=True)
class SlippageGateDecision:
    """Pure verdict of the tiered slippage gate for one LIVE candidate.

    ``rejected`` is True only for a HALT tier or a size-cap breach — the two
    fail-closed outcomes. WATCH and GREEN pass (``rejected=False``); WATCH simply
    carries the tier so the caller can emit the log + alert. ``reason`` is a
    stable, snake-case token suitable for a ``GateResult.reason`` /
    structured-log field.
    """

    tier: SlippageTier
    rejected: bool
    reason: str
    slippage_frac_of_edge: float | None
    size_cap_usdc: float | None
    size_cap_breached: bool


def normalise_cell(cell: str | None) -> str | None:
    """Canonicalise a cell label to the ``"{asset}/{timeframe}"`` lower-case key.

    Returns ``None`` for an empty / missing cell so callers can branch on
    "cell unknown" without a per-cell policy applying.
    """
    if not cell:
        return None
    norm = cell.strip().lower()
    return norm or None


def live_size_cap_for_cell(cell: str | None) -> float | None:
    """Per-cell LIVE size cap (USDC), or ``None`` when the cell has no cap.

    A ``None`` result means "no per-cell cap defined for this cell" (unknown or
    out-of-scope cell), NOT "cap of zero" — the caller must not treat ``None`` as
    a reject.
    """
    norm = normalise_cell(cell)
    if norm is None:
        return None
    return LIVE_SIZE_CAPS_USDC.get(norm)


def classify_slippage_tier(
    slippage_bps: float, gross_edge_bps: float | None
) -> SlippageTier:
    """Classify slippage as a fraction of gross edge into GREEN / WATCH / HALT.

    A non-finite slippage, or a non-positive / non-finite / missing gross edge,
    means the candidate has no measurable edge to absorb the slippage cost — a
    fail-closed HALT (you cannot pay slippage out of zero edge). Otherwise the
    ratio ``slippage_bps / gross_edge_bps`` is bucketed against the locked tiers.
    """
    if (
        gross_edge_bps is None
        or not math.isfinite(gross_edge_bps)
        or gross_edge_bps <= 0.0
        or not math.isfinite(slippage_bps)
    ):
        return SlippageTier.HALT
    frac = slippage_bps / gross_edge_bps
    if frac <= SLIPPAGE_GREEN_MAX_FRAC:
        return SlippageTier.GREEN
    if frac <= SLIPPAGE_WATCH_MAX_FRAC:
        return SlippageTier.WATCH
    return SlippageTier.HALT


def evaluate_slippage_gate(
    *,
    cell: str | None,
    proposed_size_usdc: float,
    slippage_bps: float,
    gross_edge_bps: float | None,
) -> SlippageGateDecision:
    """Pure tiered slippage verdict for one LIVE candidate.

    Order of checks (fail-closed first):

      1. **Per-cell LIVE size cap** — if the cell has a cap and the proposed size
         exceeds it, reject (``slippage_live_size_cap``). The sizing engine is
         expected to size within the cap; a breach here is a backstop against a
         misconfigured live size, mirroring the complete-set hard-cap reject.
      2. **Slippage-of-edge tier** — classify ``slippage_bps / gross_edge_bps``:
         HALT rejects (``slippage_halt``); WATCH and GREEN pass.

    ``slippage_frac_of_edge`` is populated whenever ``gross_edge_bps`` is a
    positive finite number (so the caller can log it even on a HALT), else
    ``None``.
    """
    size_cap = live_size_cap_for_cell(cell)
    frac: float | None = None
    if (
        gross_edge_bps is not None
        and math.isfinite(gross_edge_bps)
        and gross_edge_bps > 0.0
        and math.isfinite(slippage_bps)
    ):
        frac = slippage_bps / gross_edge_bps

    # 1. Per-cell LIVE size cap (fail-closed backstop).
    if size_cap is not None and proposed_size_usdc > size_cap:
        return SlippageGateDecision(
            tier=classify_slippage_tier(slippage_bps, gross_edge_bps),
            rejected=True,
            reason="slippage_live_size_cap",
            slippage_frac_of_edge=frac,
            size_cap_usdc=size_cap,
            size_cap_breached=True,
        )

    # 2. Slippage-of-edge tier.
    tier = classify_slippage_tier(slippage_bps, gross_edge_bps)
    if tier is SlippageTier.HALT:
        return SlippageGateDecision(
            tier=tier,
            rejected=True,
            reason="slippage_halt",
            slippage_frac_of_edge=frac,
            size_cap_usdc=size_cap,
            size_cap_breached=False,
        )
    return SlippageGateDecision(
        tier=tier,
        rejected=False,
        reason="slippage_watch" if tier is SlippageTier.WATCH else "slippage_green",
        slippage_frac_of_edge=frac,
        size_cap_usdc=size_cap,
        size_cap_breached=False,
    )


__all__ = [
    "SLIPPAGE_GREEN_MAX_FRAC",
    "SLIPPAGE_WATCH_MAX_FRAC",
    "LIVE_SIZE_CAPS_USDC",
    "SlippageTier",
    "SlippageGateDecision",
    "normalise_cell",
    "live_size_cap_for_cell",
    "classify_slippage_tier",
    "evaluate_slippage_gate",
]
