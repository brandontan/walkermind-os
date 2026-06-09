"""WARP-87 follow-up (smart-strike-cell-cap-binding) — close GAP B.

The WARP-87 per-cell LIVE size caps + slippage tier gate live in
``domain/risk/slippage_gate.py`` and are consumed by ``domain/risk/gate.py``
step 14b via ``ctx.cell`` / ``ctx.orderbook_depth_usdc`` / ``ctx.spread``. Before
this lane the TradeEngine path never populated those GateContext fields, so on
real flow ``ctx.cell`` was always None → the per-cell caps (btc/5m $500,
eth/5m $100) silently never fired and the slippage estimate ran on fallback
inputs.

This lane threads the Smart Strike candidate's measured cell + order-book
depth/spread:

    SignalCandidate.metadata  (late_entry_v3 stamps cell/orderbook_depth_usdc/spread)
        -> signal_scan_job._build_trade_signal  (reads them off cand.metadata)
        -> TradeSignal.cell / .orderbook_depth_usdc / .spread
        -> TradeEngine._build_gate_context
        -> GateContext.cell / .orderbook_depth_usdc / .spread
        -> gate.evaluate step 14b -> evaluate_slippage_gate(cell=ctx.cell, ...)

These tests pin:
  * the TradeSignal → GateContext threading (the gap that was missing),
  * TradeSignal back-compat defaults (None) for legacy callers,
  * the per-cell LIVE cap BINDS for btc/5m, eth/5m AND the new sol/5m — a size
    above the cap rejects with ``slippage_live_size_cap``; a size at/under the
    cap passes that check (exactly the call gate.evaluate makes with ctx.cell),
  * None-safety: cell=None → no per-cell cap applied (legacy / non-Smart-Strike
    candidate) — no regression.

Hermetic — pure functions + a SimpleNamespace; no DB, no broker, no network,
no async.
"""
from __future__ import annotations

from types import SimpleNamespace

from projects.polymarket.crusaderbot.domain.risk.slippage_gate import (
    evaluate_slippage_gate,
    live_size_cap_for_cell,
)
from projects.polymarket.crusaderbot.services.trade_engine.engine import (
    TradeEngine,
    TradeSignal,
)

# LIVE_SIZE_CAPS_USDC locked values (incl. sol/5m=$100) are asserted in
# tests/test_slippage_gate.py::test_live_size_caps_locked_values — no module-level
# assert here (a top-level assert runs at import and would break test discovery).


def _signal_ns(
    *,
    cell: str | None,
    orderbook_depth_usdc: float | None,
    spread: float | None,
) -> SimpleNamespace:
    # _build_gate_context only reads attributes — a namespace is sufficient.
    fields = dict(
        user_id="u", telegram_user_id=1, role="user", auto_trade_on=True,
        paused=False, market_id="m", side="yes", proposed_size_usdc=10,
        price=0.5, market_liquidity=1000.0, market_status="active", edge_bps=100,
        signal_ts=None, idempotency_key="k", strategy_type="late_entry_v3",
        risk_profile="balanced", daily_loss_override=None, trading_mode="live",
        user_min_liquidity=0.0, max_drawdown_pct=None, live_capital_cap_usdc=0.0,
        max_concurrent_override=None, bypass_auto_trade_check=False,
        capital_alloc_pct=None, module_live_eligible=True, active_preset=None,
        # F1 (smart-strike-slippage-edge-gate): default back-compat value; the
        # threading test overrides it explicitly.
        require_measured_edge=True,
        # Option 3 (smart-strike-real-edge): measured slippage gross-edge (bps).
        slippage_gross_edge_bps=None,
        # WARP-87 follow-up: the fields this lane threads.
        cell=cell,
        orderbook_depth_usdc=orderbook_depth_usdc,
        spread=spread,
    )
    return SimpleNamespace(**fields)


# ── TradeSignal → GateContext threading (the closed gap) ──────────────────────
def test_signal_threads_cell_depth_spread_into_gate_context():
    ctx = TradeEngine._build_gate_context(
        _signal_ns(cell="btc/5m", orderbook_depth_usdc=12_345.0, spread=0.97)
    )
    assert ctx.cell == "btc/5m"
    assert ctx.orderbook_depth_usdc == 12_345.0
    assert ctx.spread == 0.97


def test_signal_threads_none_when_candidate_omits_them():
    ctx = TradeEngine._build_gate_context(
        _signal_ns(cell=None, orderbook_depth_usdc=None, spread=None)
    )
    assert ctx.cell is None
    assert ctx.orderbook_depth_usdc is None
    assert ctx.spread is None


def test_trade_signal_defaults_cell_depth_spread_none():
    # Back-compat: callers that omit the new fields get None (legacy /
    # non-Smart-Strike / fast_topup path → gate's existing fallback applies).
    sig = TradeSignal(
        user_id="u", telegram_user_id=1, role="user", auto_trade_on=True,
        paused=False, market_id="m", market_question=None, yes_token_id=None,
        no_token_id=None, side="yes", proposed_size_usdc=10, price=0.5,
        market_liquidity=1000.0, market_status="active", idempotency_key="k",
        strategy_type="x", risk_profile="balanced", trading_mode="paper",
    )
    assert sig.cell is None
    assert sig.orderbook_depth_usdc is None
    assert sig.spread is None


# ── per-cell LIVE cap BINDS on ctx.cell (the call gate.evaluate makes) ─────────
# gate.evaluate step 14b runs ONLY for chosen_mode='live' and calls
# evaluate_slippage_gate(cell=ctx.cell, proposed_size_usdc=final_size, ...).
# A GREEN slippage (slippage_bps small vs gross_edge_bps) isolates the size cap
# as the only thing that can reject, so a breach proves the per-cell cap binds.
_GREEN_SLIP_BPS = 5.0      # 5 / 1000 = 0.5% of edge → GREEN
_GROSS_EDGE_BPS = 1000.0


def _decide(cell: str, size: float):
    return evaluate_slippage_gate(
        cell=cell,
        proposed_size_usdc=size,
        slippage_bps=_GREEN_SLIP_BPS,
        gross_edge_bps=_GROSS_EDGE_BPS,
    )


def test_btc_5m_cap_binds_above_and_passes_under():
    assert live_size_cap_for_cell("btc/5m") == 500.0
    over = _decide("btc/5m", 500.01)
    assert over.rejected is True
    assert over.reason == "slippage_live_size_cap"
    assert over.size_cap_breached is True
    under = _decide("btc/5m", 500.0)  # exact boundary passes
    assert under.rejected is False
    assert under.size_cap_breached is False


def test_eth_5m_cap_binds_above_and_passes_under():
    assert live_size_cap_for_cell("eth/5m") == 100.0
    over = _decide("eth/5m", 150.0)
    assert over.rejected is True
    assert over.reason == "slippage_live_size_cap"
    under = _decide("eth/5m", 80.0)
    assert under.rejected is False


def test_sol_5m_cap_binds_above_and_passes_under():
    # New CMD-approved cell (sol/5m = $100, conservative initial cap).
    assert live_size_cap_for_cell("sol/5m") == 100.0
    over = _decide("sol/5m", 150.0)
    assert over.rejected is True
    assert over.reason == "slippage_live_size_cap"
    under = _decide("sol/5m", 100.0)  # exact boundary passes
    assert under.rejected is False


def test_cap_binds_case_insensitively_on_normalized_cell():
    # normalize_cell_key emits "BTC/5m" (upper asset); the gate lower-cases it.
    over = _decide("BTC/5m", 600.0)
    assert over.rejected is True
    assert over.reason == "slippage_live_size_cap"


# ── None-safety: cell=None → no per-cell cap (legacy / non-Smart-Strike) ───────
def test_none_cell_applies_no_size_cap_no_regression():
    # A huge size never trips a per-cell cap when the cell is unknown; the tier
    # still applies (GREEN here) so the candidate passes.
    d = evaluate_slippage_gate(
        cell=None,
        proposed_size_usdc=1_000_000.0,
        slippage_bps=_GREEN_SLIP_BPS,
        gross_edge_bps=_GROSS_EDGE_BPS,
    )
    assert d.size_cap_usdc is None
    assert d.size_cap_breached is False
    assert d.rejected is False


def test_unknown_cell_outside_v1_set_applies_no_cap():
    # A cell outside the CMD-approved v1 set (asset or timeframe) has no cap.
    # sol/15m is now IN the set (F2); use a genuinely out-of-scope cell.
    assert live_size_cap_for_cell("doge/5m") is None
    d = _decide("doge/5m", 1_000_000.0)
    assert d.size_cap_usdc is None
    assert d.rejected is False


def test_15m_cell_cap_binds_after_f2():
    # F2 (2026-06-08): 15m cells are now capped (btc/15m $500, eth/15m $100).
    assert live_size_cap_for_cell("btc/15m") == 500.0
    assert live_size_cap_for_cell("eth/15m") == 100.0
    assert live_size_cap_for_cell("sol/15m") == 100.0
    over = _decide("eth/15m", 150.0)
    assert over.rejected is True
    assert over.reason == "slippage_live_size_cap"
    under = _decide("btc/15m", 500.0)
    assert under.rejected is False


def test_require_measured_edge_threads_signal_to_gate_context():
    # F1: TradeSignal.require_measured_edge → GateContext.require_measured_edge.
    sig = _signal_ns(cell="btc/5m", orderbook_depth_usdc=1000.0, spread=1.0)
    sig.require_measured_edge = False
    ctx = TradeEngine._build_gate_context(sig)
    assert ctx.require_measured_edge is False


def test_slippage_gross_edge_bps_threads_signal_to_gate_context():
    # Option 3: TradeSignal.slippage_gross_edge_bps → GateContext.slippage_gross_edge_bps.
    sig = _signal_ns(cell="btc/5m", orderbook_depth_usdc=1000.0, spread=1.0)
    sig.slippage_gross_edge_bps = 450.0
    ctx = TradeEngine._build_gate_context(sig)
    assert ctx.slippage_gross_edge_bps == 450.0


def test_trade_signal_defaults_slippage_gross_edge_bps_none():
    # Back-compat: legacy callers omit it → None (gate uses ctx.edge_bps).
    sig = TradeSignal(
        user_id="u", telegram_user_id=1, role="user", auto_trade_on=True,
        paused=False, market_id="m", market_question=None, yes_token_id=None,
        no_token_id=None, side="yes", proposed_size_usdc=10, price=0.5,
        market_liquidity=1000.0, market_status="active", idempotency_key="k",
        strategy_type="x", risk_profile="balanced", trading_mode="paper",
    )
    assert sig.slippage_gross_edge_bps is None


def test_trade_signal_defaults_require_measured_edge_true():
    # Back-compat: legacy callers that omit the field get the prior HALT-on-no-edge.
    sig = TradeSignal(
        user_id="u", telegram_user_id=1, role="user", auto_trade_on=True,
        paused=False, market_id="m", market_question=None, yes_token_id=None,
        no_token_id=None, side="yes", proposed_size_usdc=10, price=0.5,
        market_liquidity=1000.0, market_status="active", idempotency_key="k",
        strategy_type="x", risk_profile="balanced", trading_mode="paper",
    )
    assert sig.require_measured_edge is True
