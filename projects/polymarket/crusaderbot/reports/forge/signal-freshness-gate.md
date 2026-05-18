# WARP•FORGE REPORT — signal-freshness-gate

**Branch:** WARP/CRUSADERBOT-SIGNAL-FRESHNESS-GATE
**Date:** 2026-05-18
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** _process_candidate() freshness gate in signal_scan_job.py
**Not in Scope:** DB schema changes, signal_publications.expires_at, feed UI, lib strategy signal_ts handling

---

## 1. What Was Built

Added a signal freshness gate (step 1c) to `_process_candidate()` in `signal_scan_job.py`.

The gate rejects any `SignalCandidate` whose `signal_ts` is older than `_MAX_SIGNAL_AGE_SECONDS` (1800s / 30 minutes). Signals exceeding this threshold are skipped with `outcome="skipped_signal_stale"` logged via structlog. No DB writes occur on the skip path.

Root cause addressed: `signal_publications.expires_at` is set to 4 hours after `published_at` — correct for feed UI history, but the execution engine had no tighter window. Signals published 3+ hours ago were being consumed with stale entry prices, causing instant TP on paper fills (all 13 trades today closed in < 20 seconds; entry prices 0.05–0.25 vs current price 0.575).

---

## 2. Current System Architecture

```
signal_scan_job.run_once()
  └── Phase C: evaluate_publications_for_user() -> feed_candidates
        └── _process_candidate(row, cand)
              0. Crash-recovery resume (stale 'queued' row)
              1. Permanent dedup (execution_queue)
              1b. Open-position market dedup
              1c. [NEW] Signal freshness gate (age > 1800s → skip)
              2. Market lookup
              2b. Liquidity filter
              3. Build TradeSignal
              4. TradeEngine.execute() (13-step risk gate + paper fill)
              5. Record in execution_queue
```

Lib strategy candidates (Phase B) also flow through `_process_candidate`. Those use `signal_ts=now` (always fresh), so the gate is a no-op for them in practice.

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
  - Line 41: added `from datetime import datetime, timezone` to module-level imports
  - Lines 67–72: added `_MAX_SIGNAL_AGE_SECONDS: int = 1800` constant with docstring
  - Lines 325–328: removed local `from datetime import datetime, timezone` (now redundant)
  - Lines 506–519: added step 1c freshness gate block

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/signal-freshness-gate.md` (this file)

---

## 4. What Is Working

- `_MAX_SIGNAL_AGE_SECONDS = 1800` constant defined in constants block.
- Freshness gate runs after step 1b (open-position dedup), before step 2 (market lookup).
- `log.info(outcome="skipped_signal_stale", age_seconds=..., threshold=...)` emitted on skip.
- Pure arithmetic — no new try/catch needed, cannot throw.
- `datetime` import is module-level (not inline).
- Crash-recovery path (step 0) runs before the freshness gate — stale 'queued' rows are not blocked.
- Lib strategy candidates (Phase B, `signal_ts=now`) are unaffected.
- No DB schema changes.

---

## 5. Known Issues

None introduced by this change.

---

## 6. What Is Next

**Suggested Next Step:** WARP🔹CMD review required. No SENTINEL run needed (STANDARD tier). After merge, monitor structlog for `outcome="skipped_signal_stale"` events to confirm old publications are being filtered. If 30-minute window proves too tight for fast-moving signal feeds, `_MAX_SIGNAL_AGE_SECONDS` can be tuned without further schema changes.
