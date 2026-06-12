# WARP•R00T — live-smart-strike-no-trade-diagnostic

Branch: `WARP/live-smart-strike-no-trade-diagnostic`
Issue: #1804
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Role: WARP•R00T (owner-assigned)
Date: 2026-06-12 (Asia/Jakarta)

Validation Target: Diagnose production LIVE Smart Strike running with no
scans/signals/trades and ensure fail-closed reasons are visible without forcing
live orders.

Not in Scope: live-fire order placement, forced trade, strategy rewrite,
risk/reward redesign, deposit/withdraw changes, live-guard flag flips, real fund
movement.

---

## 1. What was built

A read-only observability surface that exposes the REAL Smart Strike candle-scan
funnel and its **dominant no-trade reason** to the WebTrader / operator runtime
status panel. Previously a LIVE Smart Strike state that was failing closed for an
explicit, already-recorded reason could only render `awaiting_signal` + `scanned
0 / published 0`, because those panel counters come from the legacy edge-finder
scanner, not from Smart Strike.

- New pure helper `summarize_no_trade_reason(scan_run)` derives the dominant
  no-trade reason from the persisted `scan_runs` telemetry.
- `RuntimeStatus` schema + `/status` endpoint now carry the Smart Strike funnel
  counts and the dominant reason.
- The frontend ScannerPanel renders the reason in the status line instead of a
  bare `awaiting_signal`.

No gating logic, order-intent path, or live guard was changed.

## 2. Root-cause statement — expected fail-closed vs bug

**Both: a correct fail-closed posture, masked by an observability bug.**

- The no-trade behaviour itself is, in the reported state, expected fail-closed
  behaviour (no eligible BTC/ETH candle edge / awaiting next candle / measured-
  edge / min-order / per-user sizing — Smart Strike is built to NOT fire without
  prerequisites). No forced trade is warranted.
- The **bug** is an observability gap: the user-facing scanner panel reads
  `scanner_scanned` / `scanner_published` from the legacy edge-finder
  (`jobs/market_signal_scanner.py` `_scanner_state`, surfaced by the `/status`
  endpoint), which is a generic momentum scanner unrelated to the Smart Strike
  candle path. The REAL Smart Strike candle scan runs in
  `services/signal_scan/signal_scan_job.py` and records rich
  `skip_breakdown` / `rejection_breakdown` / `zero_reason_breakdown` telemetry to
  the `scan_runs` table — but that telemetry was never surfaced to the user
  panel. So a fail-closed no-trade state was invisible behind `awaiting_signal` +
  `0 / 0`.

Evidence:
- `webtrader/backend/router.py` `/status` → `RuntimeStatus.scanner_scanned/published`
  sourced from `jobs/market_signal_scanner.get_scanner_state()`.
- `jobs/market_signal_scanner.py:516,550,579-581` — `edge_scanned`/`edge_published`
  are edge-finder approval/publish counts (0 on a quiet generic market), written
  to `_scanner_state`. `last_tick_ts` updates every tick → "last_tick 18s ago"
  while counts stay 0.
- `services/signal_scan/signal_scan_job.py:709-741` (`ScanTelemetry`),
  `:1918-1956` (`_finish_scan_run` persists skip/rejection/zero breakdowns),
  `:250-281` (`_smart_strike_admin_universe` emits explicit skip reasons),
  `:1959-1988` (`fetch_latest_scan_run`) — full reason telemetry existed but was
  not read by the user panel.

## 3. Current system architecture (changed surface only)

```
signal_scan_job (Smart Strike candle scan)
  └─ ScanTelemetry → _finish_scan_run → scan_runs (skip/rejection/zero breakdowns)
       └─ fetch_latest_scan_run()                       [pre-existing, read-only]
            └─ summarize_no_trade_reason(scan_run)       [NEW pure helper]
                 └─ /status (router) → RuntimeStatus      [NEW fields, read-only]
                      └─ ScannerPanel.tsx status line     [NEW: explicit reason]
```

Dominant reason = highest-count entry across the three breakdowns; falls back to
a structural funnel reason (`no_markets_in_universe` / `no_eligible_markets` /
`no_candidates` / `awaiting_signal`) when no per-candidate breakdown exists.
Returns `None` when a trade fired or no scan data exists (panel shows
`signal_fired` / `awaiting_signal`).

## 4. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  — added `summarize_no_trade_reason()` (pure, read-only).
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py`
  — `RuntimeStatus` gains optional Smart Strike funnel + `smart_strike_no_trade_reason` + `scan_run_at`.
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  — `/status` reads `fetch_latest_scan_run()` + `summarize_no_trade_reason()` (non-fatal).
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
  — `RuntimeStatus` TS type gains the optional fields.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/ScannerPanel.tsx`
  — status line shows `awaiting_signal · <reason>` from telemetry.

Created:
- `projects/polymarket/crusaderbot/tests/test_smart_strike_no_trade_reason.py`
- `projects/polymarket/crusaderbot/reports/forge/live-smart-strike-no-trade-diagnostic.md` (this report)

## 5. What is working

- `summarize_no_trade_reason` verified against 16 cases (dominant-reason
  selection across all three breakdowns, JSON-string coercion, deterministic tie
  break, trade-fired → None, structural funnel fallbacks, and the diagnostic pin
  that zeros cannot hide skip reasons) — exercised against the real source
  function text.
- `python -m py_compile` + `ruff check` clean on all touched Python files.
- Frontend `tsc && vite build` green (888 modules).
- LIVE order-intent positive path and fail-closed negative paths remain governed
  by the unchanged gates (`domain/execution/live.py` `assert_live_guards`,
  `domain/activation/live_mode.py` $5 gate, measured-edge, min-order, kill
  switch) — covered by existing `tests/test_smart_strike_audit_gaps.py`,
  `tests/test_live_gate_hardening.py`, `tests/test_slippage_gate.py`,
  `tests/test_router_global_live_gate.py`. This lane adds telemetry only and does
  not touch them.

## 6. Known issues

- The local scratch environment cannot install the full Polymarket SDK chain
  (`py_clob_client_v2` et al.), so the package-importing test modules
  (including this lane's new test) are validated by GitHub CI, which installs
  `[project.dependencies]`. The new helper's logic was independently proven
  locally by exercising the extracted source function (16/16).
- The legacy `scanner_scanned` / `scanner_published` counters are retained as-is
  (edge-finder semantics: approved/published, not markets-evaluated). Renaming
  was deliberately avoided as out-of-scope contract risk; the Smart Strike funnel
  is added alongside instead.

---

## Safety invariant statement

No live-guard flag was flipped (`USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`,
`ENABLE_LIVE_TRADING`, `CAPITAL_MODE_CONFIRMED` untouched). No real order placed,
no funds moved, no signal fabricated. Auto-Trade, per-user balance, measured-edge,
min-order, kill-switch, and CLOB credential checks are unchanged. The new surface
is strictly read-only telemetry derived from already-persisted `scan_runs` rows;
it never influences gating or order generation. No secrets written to repo, logs,
report, PR body, or fixtures.

## Suggested Next Step

WARP🔹CMD first-pass PR check, then WARP•R00T final-gate disposition. Because this
is a MAJOR live-readiness diagnostic that adds observability only (no execution
path change) and all safety invariants hold, WARP•R00T may take final-gate
responsibility on CI green, or route to WARP•SENTINEL before merge.
