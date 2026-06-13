"""WARP•R00T — live-smart-strike-no-trade-diagnostic.

Pins for the no-trade-reason observability surface. The WebTrader / operator
scanner panel previously could only show ``awaiting_signal`` + ``scanned 0 /
published 0`` (legacy edge-finder counters) for a LIVE Smart Strike state that
was actually failing closed for an explicit, already-recorded reason. These
tests pin that:

1. ``summarize_no_trade_reason`` derives the dominant reason from the REAL
   Smart Strike ``scan_runs`` telemetry (skip / rejection / zero-reason
   breakdowns, or a structural funnel fallback) — purely read-only.
2. A no-trade scan run with zero orders CANNOT hide its skip reasons behind
   zero counters (the core diagnostic guarantee).
3. The user-facing ``/status`` endpoint + RuntimeStatus schema + ScannerPanel
   UI are wired to surface the dominant reason.

Pure unit + source-level pins: no DB, no network, no live guards touched.
"""
from __future__ import annotations

import json
import pathlib

from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    summarize_no_trade_reason,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _run(**over: object) -> dict[str, object]:
    """A finished scan_runs row with no orders/positions by default."""
    base: dict[str, object] = {
        "paper_orders_created": 0,
        "positions_created": 0,
        "markets_seen": 5,
        "markets_eligible": 3,
        "candidates_emitted": 2,
        "skip_breakdown": {},
        "rejection_breakdown": {},
        "zero_reason_breakdown": {},
    }
    base.update(over)
    return base


# ── dominant-reason selection ───────────────────────────────────────────────


def test_dominant_reason_from_skip_breakdown() -> None:
    run = _run(skip_breakdown={"skipped_stale_tob": 2, "skipped_liquidity": 5})
    assert summarize_no_trade_reason(run) == "skipped_liquidity"


def test_rejection_breakdown_used_when_skip_empty() -> None:
    run = _run(rejection_breakdown={"step_14_below_min_order_shares": 4})
    assert summarize_no_trade_reason(run) == "step_14_below_min_order_shares"


def test_zero_reason_breakdown_used() -> None:
    run = _run(zero_reason_breakdown={"late_entry_v3:measured_edge_missing": 3})
    assert summarize_no_trade_reason(run) == "late_entry_v3:measured_edge_missing"


def test_merged_breakdowns_highest_count_wins() -> None:
    run = _run(
        skip_breakdown={"skipped_liquidity": 2},
        rejection_breakdown={"step_14_below_min_order_shares": 9},
        zero_reason_breakdown={"late_entry_v3:no_edge": 1},
    )
    assert summarize_no_trade_reason(run) == "step_14_below_min_order_shares"


def test_tie_breaks_deterministically_alphabetical() -> None:
    run = _run(skip_breakdown={"skipped_zeta": 3, "skipped_alpha": 3})
    # Equal counts → alphabetically-first reason, deterministic across runs.
    assert summarize_no_trade_reason(run) == "skipped_alpha"


def test_json_string_breakdown_is_coerced() -> None:
    # asyncpg may hand JSONB columns back as raw strings.
    run = _run(skip_breakdown=json.dumps({"smart_strike_admin_disabled": 1}))
    assert summarize_no_trade_reason(run) == "smart_strike_admin_disabled"


def test_malformed_breakdown_does_not_raise() -> None:
    run = _run(skip_breakdown="{not valid json", markets_seen=0)
    # Falls through to structural reason rather than raising.
    assert summarize_no_trade_reason(run) == "no_markets_in_universe"


# ── trade-fired → no reason ─────────────────────────────────────────────────


def test_none_when_order_fired() -> None:
    run = _run(paper_orders_created=1, skip_breakdown={"skipped_liquidity": 9})
    assert summarize_no_trade_reason(run) is None


def test_none_when_position_created() -> None:
    run = _run(positions_created=1)
    assert summarize_no_trade_reason(run) is None


def test_none_when_no_scan_run() -> None:
    assert summarize_no_trade_reason(None) is None
    assert summarize_no_trade_reason({}) is None


# ── structural funnel fallback (no per-candidate breakdown) ──────────────────


def test_structural_no_markets_in_universe() -> None:
    run = _run(markets_seen=0, markets_eligible=0, candidates_emitted=0)
    assert summarize_no_trade_reason(run) == "no_markets_in_universe"


def test_structural_no_eligible_markets() -> None:
    run = _run(markets_seen=8, markets_eligible=0, candidates_emitted=0)
    assert summarize_no_trade_reason(run) == "no_eligible_markets"


def test_structural_no_candidates() -> None:
    run = _run(markets_seen=8, markets_eligible=4, candidates_emitted=0)
    assert summarize_no_trade_reason(run) == "no_candidates"


def test_structural_awaiting_signal_when_funnel_full_but_no_order() -> None:
    run = _run(markets_seen=8, markets_eligible=4, candidates_emitted=2)
    assert summarize_no_trade_reason(run) == "awaiting_signal"


# ── required pin: zeros cannot hide skip reasons ────────────────────────────


def test_zeros_cannot_hide_skip_reasons() -> None:
    """scanner 0/0 (no orders) MUST still surface an explicit reason.

    Reproduces the production-reported state: scanner running, no order, skip
    reasons recorded. The diagnostic guarantee is that the dominant reason is
    non-None and explicit (never silently empty).
    """
    diagnostic = _run(
        paper_orders_created=0,
        positions_created=0,
        skip_breakdown={
            "smart_strike_admin_disabled": 0,
            "skipped_orderbook_empty": 6,
            "skipped_below_min_order_size": 2,
        },
    )
    reason = summarize_no_trade_reason(diagnostic)
    assert reason is not None
    assert reason == "skipped_orderbook_empty"


# ── required pin: user-facing telemetry surfaces the reason ─────────────────


def test_runtime_status_schema_exposes_no_trade_reason() -> None:
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import RuntimeStatus

    fields = RuntimeStatus.model_fields
    for name in (
        "smart_strike_no_trade_reason",
        "smart_strike_markets_seen",
        "smart_strike_markets_eligible",
        "smart_strike_orders",
        "scan_run_at",
    ):
        assert name in fields, f"RuntimeStatus must expose {name}"


def test_status_endpoint_wires_no_trade_reason() -> None:
    """The /status handler must populate the reason from real scan telemetry."""
    src = (_ROOT / "webtrader/backend/router.py").read_text(encoding="utf-8")
    assert "summarize_no_trade_reason" in src
    assert "fetch_latest_scan_run" in src
    assert "smart_strike_no_trade_reason=ss_reason" in src


def test_scanner_panel_renders_no_trade_reason() -> None:
    src = (_ROOT / "webtrader/frontend/src/components/ScannerPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "smart_strike_no_trade_reason" in src
    # The status line must consume the derived reason, not a bare literal.
    assert "statusText" in src


def test_scanner_panel_formats_no_trade_reason_as_friendly_copy() -> None:
    """Owner-locked Smart Strike no-trade copy + idle scan animation pins (#1807).

    Pins:
    - Headline is the owner-approved "Waiting for a valid signal" (no "setup").
    - Category-based mapping for orderbook / strength / sizing / live-gate /
      eligibility / late-entry — raw backend codes never leak to user copy.
    - Idle subtle scan animation (ScanDots / animate-scan-dot) is rendered
      only when the scanner is active and no signal has fired.
    - The previous inline `skipped_` trim is gone, and there is no `setup`
      wording in the user-visible category labels.
    """
    src = (_ROOT / "webtrader/frontend/src/components/ScannerPanel.tsx").read_text(
        encoding="utf-8"
    )
    # Formatter is consumed by the panel.
    assert "formatNoTradeReason(noTradeReason)" in src
    # Owner-locked headline + unknown fallback.
    assert "Waiting for a valid signal" in src
    assert "Still scanning for a valid signal" in src
    # Owner-locked category copy.
    assert "No matching signal yet" in src
    assert "Signal strength is not strong enough yet" in src
    assert "Market liquidity is not ready yet" in src
    assert "Trade size is below the minimum required" in src
    assert "Live trading requirements are not fully met" in src
    assert "Market is not eligible right now" in src
    assert "Entry window is too short right now" in src
    # Owner explicitly removed "setup" wording from user-visible Smart Strike copy.
    for forbidden in (
        "waiting for a clean setup",
        "late-entry filter blocked setup",
        "no qualifying setup yet",
    ):
        assert forbidden not in src.lower(), f"forbidden user copy still present: {forbidden}"
    # No more inline ad-hoc "skipped_" trim — formatter owns the prefix strip.
    assert 'noTradeReason.replace(/^skipped_/' not in src
    # Idle scan animation wired (lightweight dots, only when no signal).
    assert "animate-scan-dot" in src
    assert "function ScanDots" in src
    assert "signals.length === 0 ? <ScanDots />" in src


def test_index_css_defines_scan_dot_keyframe() -> None:
    """The subtle scanning-dot animation must be defined in index.css (#1807)."""
    src = (_ROOT / "webtrader/frontend/src/index.css").read_text(encoding="utf-8")
    assert "@keyframes scanDot" in src
    assert ".animate-scan-dot" in src
