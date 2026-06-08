"""WARP-87 — tiered LIVE-cutover slippage gate tests.

Covers the pure RISK-stage slippage gate (domain/risk/slippage_gate.py): the
GREEN / WATCH / HALT tier classifier, the per-cell LIVE size caps, and the
combined ``evaluate_slippage_gate`` verdict — one test per tier using mock
slippage values, plus the size-cap backstop and a realistic estimator → gate
integration. Hermetic — pure functions, no DB, no network, no async.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.domain.research.slippage_estimator import (
    estimate_slippage_bps,
)
from projects.polymarket.crusaderbot.domain.risk.slippage_gate import (
    LIVE_SIZE_CAPS_USDC,
    SLIPPAGE_GREEN_MAX_FRAC,
    SLIPPAGE_WATCH_MAX_FRAC,
    SlippageTier,
    classify_slippage_tier,
    evaluate_slippage_gate,
    live_size_cap_for_cell,
    normalise_cell,
)

# Locked Sub-Lane C tiers (PR #1691; owner pick WARP-87).
assert SLIPPAGE_GREEN_MAX_FRAC == 0.15
assert SLIPPAGE_WATCH_MAX_FRAC == 0.30


# ── tier classifier — one test per tier (mock slippage values) ────────────────
def test_classify_green():
    # 10% of edge (100 bps slip / 1000 bps edge) → well under 15% → GREEN.
    assert classify_slippage_tier(100.0, 1000.0) is SlippageTier.GREEN


def test_classify_watch():
    # 22% of edge (220 / 1000) → between 15% and 30% → WATCH.
    assert classify_slippage_tier(220.0, 1000.0) is SlippageTier.WATCH


def test_classify_halt():
    # 39.5% of edge (the proposal's eth/5m-at-$5k case) → over 30% → HALT.
    assert classify_slippage_tier(395.0, 1000.0) is SlippageTier.HALT


def test_classify_tier_boundaries_are_inclusive_on_lower_tier():
    # Exactly 15% is GREEN; exactly 30% is WATCH; a hair over 30% is HALT.
    assert classify_slippage_tier(150.0, 1000.0) is SlippageTier.GREEN
    assert classify_slippage_tier(300.0, 1000.0) is SlippageTier.WATCH
    assert classify_slippage_tier(300.01, 1000.0) is SlippageTier.HALT


def test_classify_halt_on_nonpositive_or_missing_edge():
    # No measurable edge to absorb slippage → fail-closed HALT.
    assert classify_slippage_tier(10.0, 0.0) is SlippageTier.HALT
    assert classify_slippage_tier(10.0, -50.0) is SlippageTier.HALT
    assert classify_slippage_tier(10.0, None) is SlippageTier.HALT


def test_classify_halt_on_nonfinite_inputs():
    assert classify_slippage_tier(float("nan"), 1000.0) is SlippageTier.HALT
    assert classify_slippage_tier(float("inf"), 1000.0) is SlippageTier.HALT
    assert classify_slippage_tier(10.0, float("inf")) is SlippageTier.HALT


# ── per-cell LIVE size caps ───────────────────────────────────────────────────
def test_live_size_caps_locked_values():
    # CMD-approved LIVE v1 cell set: BTC + ETH + SOL on 5m AND 15m (F2,
    # 2026-06-08). 15m mirrors 5m as a conservative initial cap (longer candle
    # window → strictly deeper book), pending live-fill tuning.
    assert LIVE_SIZE_CAPS_USDC == {
        "btc/5m": 500.0,
        "eth/5m": 100.0,
        "sol/5m": 100.0,
        "btc/15m": 500.0,
        "eth/15m": 100.0,
        "sol/15m": 100.0,
    }
    assert live_size_cap_for_cell("btc/5m") == 500.0
    assert live_size_cap_for_cell("eth/5m") == 100.0
    assert live_size_cap_for_cell("sol/5m") == 100.0
    # F2: 15m cells now carry per-cell LIVE caps too.
    assert live_size_cap_for_cell("btc/15m") == 500.0
    assert live_size_cap_for_cell("eth/15m") == 100.0
    assert live_size_cap_for_cell("sol/15m") == 100.0


def test_live_size_cap_unknown_cell_returns_none():
    # A cell outside the CMD-approved v1 set (asset or timeframe) has no cap.
    assert live_size_cap_for_cell("doge/5m") is None
    assert live_size_cap_for_cell("btc/1m") is None
    assert live_size_cap_for_cell(None) is None
    assert live_size_cap_for_cell("") is None


def test_normalise_cell_case_and_whitespace_insensitive():
    assert normalise_cell("  BTC/5m ") == "btc/5m"
    assert normalise_cell("ETH/5M") == "eth/5m"
    assert normalise_cell(None) is None
    assert live_size_cap_for_cell(" BTC/5M ") == 500.0


# ── evaluate_slippage_gate — combined verdict, one per tier ───────────────────
def test_evaluate_green_passes():
    d = evaluate_slippage_gate(
        cell="btc/5m", proposed_size_usdc=100.0,
        slippage_bps=90.0, gross_edge_bps=1436.0,  # ~6% of edge
    )
    assert d.tier is SlippageTier.GREEN
    assert d.rejected is False
    assert d.reason == "slippage_green"
    assert d.size_cap_breached is False


def test_evaluate_watch_passes_with_tier():
    d = evaluate_slippage_gate(
        cell="eth/5m", proposed_size_usdc=80.0,
        slippage_bps=120.0, gross_edge_bps=612.0,  # ~19.6% of edge
    )
    assert d.tier is SlippageTier.WATCH
    assert d.rejected is False
    assert d.reason == "slippage_watch"
    assert d.slippage_frac_of_edge is not None


def test_evaluate_halt_rejects_cleanly():
    d = evaluate_slippage_gate(
        cell="eth/5m", proposed_size_usdc=50.0,
        slippage_bps=242.0, gross_edge_bps=612.0,  # ~39.5% of edge
    )
    assert d.tier is SlippageTier.HALT
    assert d.rejected is True
    assert d.reason == "slippage_halt"
    # frac is still populated on HALT so the caller can log it.
    assert d.slippage_frac_of_edge is not None and d.slippage_frac_of_edge > 0.30


def test_evaluate_size_cap_breach_rejects():
    # eth/5m cap is $100; a $150 live size is a fail-closed backstop reject even
    # though the slippage-of-edge would otherwise be GREEN.
    d = evaluate_slippage_gate(
        cell="eth/5m", proposed_size_usdc=150.0,
        slippage_bps=10.0, gross_edge_bps=612.0,
    )
    assert d.rejected is True
    assert d.reason == "slippage_live_size_cap"
    assert d.size_cap_breached is True
    assert d.size_cap_usdc == 100.0


def test_evaluate_size_cap_exact_boundary_passes():
    # Exactly at the cap is allowed (cap is a ceiling, breach is strictly over).
    d = evaluate_slippage_gate(
        cell="eth/5m", proposed_size_usdc=100.0,
        slippage_bps=10.0, gross_edge_bps=612.0,
    )
    assert d.rejected is False
    assert d.size_cap_breached is False


def test_evaluate_unknown_cell_has_no_size_cap():
    # No per-cell cap for an out-of-scope cell — size never rejects; tier still applies.
    d = evaluate_slippage_gate(
        cell="doge/5m", proposed_size_usdc=10_000.0,
        slippage_bps=50.0, gross_edge_bps=1000.0,
    )
    assert d.size_cap_usdc is None
    assert d.size_cap_breached is False
    assert d.tier is SlippageTier.GREEN
    assert d.rejected is False


def test_evaluate_halt_on_missing_edge_even_under_size_cap():
    # Default (require_measured_edge=True, back-compat): no edge → HALT even under cap.
    d = evaluate_slippage_gate(
        cell="btc/5m", proposed_size_usdc=50.0,
        slippage_bps=20.0, gross_edge_bps=None,
    )
    assert d.tier is SlippageTier.HALT
    assert d.rejected is True
    assert d.reason == "slippage_halt"
    assert d.slippage_frac_of_edge is None


# ── F1: cap-only fallback for an unmeasured edge (Smart Strike default) ────────
def test_cap_only_passes_capped_cell_with_no_edge():
    # require_measured_edge=False + capped cell + finite slip + no edge → the
    # per-cell $ cap is the sole LIVE control → pass (the late_entry_v3 case).
    d = evaluate_slippage_gate(
        cell="btc/5m", proposed_size_usdc=50.0,
        slippage_bps=20.0, gross_edge_bps=None,
        require_measured_edge=False,
    )
    assert d.rejected is False
    assert d.tier is SlippageTier.GREEN
    assert d.reason == "slippage_cap_only_no_edge"
    assert d.size_cap_usdc == 500.0
    assert d.slippage_frac_of_edge is None


def test_cap_only_still_enforces_the_size_cap():
    # Cap-only mode does NOT relax the per-cell $ cap: a size over the cap still
    # rejects (the cap is the whole point of allowing a no-edge entry).
    d = evaluate_slippage_gate(
        cell="eth/5m", proposed_size_usdc=150.0,
        slippage_bps=20.0, gross_edge_bps=None,
        require_measured_edge=False,
    )
    assert d.rejected is True
    assert d.reason == "slippage_live_size_cap"
    assert d.size_cap_breached is True


def test_cap_only_halts_uncapped_cell_with_no_edge():
    # No edge + NO per-cell cap → fail-closed HALT even in cap-only mode (cap-only
    # relies on the cap as the control; without one there is nothing bounding size).
    d = evaluate_slippage_gate(
        cell="doge/5m", proposed_size_usdc=50.0,
        slippage_bps=20.0, gross_edge_bps=None,
        require_measured_edge=False,
    )
    assert d.rejected is True
    assert d.reason == "slippage_halt"


def test_cap_only_halts_capped_cell_on_nonfinite_slip():
    # A non-finite slippage estimate is a data fault → HALT even in cap-only mode.
    d = evaluate_slippage_gate(
        cell="btc/5m", proposed_size_usdc=50.0,
        slippage_bps=float("nan"), gross_edge_bps=None,
        require_measured_edge=False,
    )
    assert d.rejected is True
    assert d.reason == "slippage_halt"


def test_require_measured_edge_true_halts_capped_cell_no_edge():
    # Toggle ON (future real-edge posture): no edge → HALT even on a capped cell.
    d = evaluate_slippage_gate(
        cell="btc/15m", proposed_size_usdc=50.0,
        slippage_bps=20.0, gross_edge_bps=None,
        require_measured_edge=True,
    )
    assert d.rejected is True
    assert d.reason == "slippage_halt"


def test_cap_only_does_not_affect_measured_edge_tiers():
    # With a real measured edge, require_measured_edge=False changes nothing — the
    # tier classifier still governs (HALT here at ~39.5% of edge).
    d = evaluate_slippage_gate(
        cell="eth/5m", proposed_size_usdc=50.0,
        slippage_bps=242.0, gross_edge_bps=612.0,
        require_measured_edge=False,
    )
    assert d.tier is SlippageTier.HALT
    assert d.rejected is True
    assert d.reason == "slippage_halt"


# ── estimator → gate integration (realistic Sub-Lane C numbers) ───────────────
def test_estimator_to_gate_eth_5m_at_cap_is_green():
    # eth/5m at the $100 LIVE cap, depth ~7.2k (Sub-Lane D p50), spread 1.0104
    # (~52 bps round-trip): the proposal puts this at ~13% of the +612 bps edge
    # → strictly GREEN, validating the launch cap keeps eth/5m in GREEN.
    est = estimate_slippage_bps(
        stake_usdc=100.0, orderbook_depth_usdc=7_200.0,
        spread=1.0104, entry_price=0.5,
    )
    d = evaluate_slippage_gate(
        cell="eth/5m", proposed_size_usdc=100.0,
        slippage_bps=est.total_bps, gross_edge_bps=612.0,
    )
    assert d.tier is SlippageTier.GREEN
    assert d.rejected is False
    assert d.slippage_frac_of_edge is not None
    assert d.slippage_frac_of_edge <= SLIPPAGE_GREEN_MAX_FRAC
