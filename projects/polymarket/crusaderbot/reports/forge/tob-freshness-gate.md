# Forge Report — WARP/R00T/tob-freshness-gate

**Date:** 2026-05-30 14:11 Asia/Jakarta
**Role:** WARP•R00T
**Branch:** WARP/R00T/tob-freshness-gate
**Lane:** 1 of 5 (Polybot directive — defensive guardrails campaign)
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** late_entry_v3 candidate path (close_sweep / safe_close / flip_hunter) — entry rejection when CLOB snapshot is stale
**Not in Scope:** signal_following / momentum / copy_trade candidates (no stamp → no-op); dual-leg arbitrage; inventory tracker; bankroll dynamic sizing (Lane 5)
**Suggested Next:** WARP🔹CMD review → merge → proceed to Lane 2 (`WARP/R00T/close-sweep-spread-gate`)

---

## 1. What was built

Defensive entry guard for the three candle-market presets (`close_sweep`, `safe_close`, `flip_hunter` — all served by `late_entry_v3`). When the orderbook snapshot used to compute a candidate's `entry_price` is older than `TOB_STALE_MS` (default 2000ms) by the time `_process_candidate` is ready to fire the trade, the candidate is rejected with `scan_outcome="skipped_stale_tob"` instead of being submitted on a moved market.

This is the directional analogue of the sub-cent / Gamma-fallback guard (PR #1413). The sub-cent guard catches *wrong-source* prices; the freshness guard catches *aged* prices. Together they bracket the scan→fill latency surface.

**No change to:** strategy mechanics, risk gate, force-exit timing, paper-default invariant, activation guards, sizing path, dual-leg architecture (intentionally untouched — directive's dual-leg arch is fundamentally incompatible with current single-leg per-user multi-tenant design; deferred to a separate WARP🔹CMD scoping discussion).

**Operator escape hatch:** `TOB_STALE_MS=0` (env or config) disables the gate without redeploy. The branch is `_tob_stale_ms > 0` so the disable sentinel is unambiguous.

---

## 2. Current system architecture (relevant slice)

```
late_entry_v3._evaluate_market
    └─ fetches CLOB /book → derives yes_ask/no_ask/entry_price
    └─ NEW: stamps metadata["entry_price_ts"] = now (UTC epoch float)
    └─ returns SignalCandidate

services.signal_scan.signal_scan_job._process_candidate
    └─ step 3a: dedup / open-position / liquidity gates
    └─ step 3b: resolve _live_fill_price from metadata or get_live_market_price
    └─ NEW step 3b-0: TOB freshness gate
        └─ read metadata["entry_price_ts"]
            ├─ missing  → no-op (signal_following / momentum / copy_trade)
            └─ present  → if age_ms > config.TOB_STALE_MS:
                            log scan_outcome=skipped_stale_tob
                            telemetry.record_skip("skipped_stale_tob")
                            return
    └─ step 3b-i: sub-cent / Gamma-fallback guard (existing)
    └─ step 3c: fill-time price-band re-check (existing)
    └─ step 4: risk gate → router → execution
```

Pipeline boundary preserved: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION. The gate lives in the INTELLIGENCE layer, before any risk or execution call.

---

## 3. Files created / modified (full repo-root paths)

| Action | File | Lines touched | Purpose |
|---|---|---|---|
| Modified | `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` | +6 | Stamp `entry_price_ts` into SignalCandidate metadata |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | +52 | New step 3b-0 freshness gate, scoped to stamped candidates |
| Modified | `projects/polymarket/crusaderbot/config.py` | +13 | New `TOB_STALE_MS: int = 2000` knob with docstring |
| Created | `projects/polymarket/crusaderbot/tests/test_tob_freshness_gate.py` | +130 | 17 hermetic tests — source pins, config knob, threshold math |
| Created | `projects/polymarket/crusaderbot/reports/forge/tob-freshness-gate.md` | this report | WARP•R00T evidence trail |

---

## 4. What is working

**Verified locally:**
- `python -m py_compile` clean on all 4 modified production files.
- `pytest projects/polymarket/crusaderbot/tests/test_tob_freshness_gate.py` — 17/17 pass (0.48s).
- Neighbor regression — `test_flip_hunter_stale_price_fix.py` + `test_late_entry_v3.py` + `test_signal_scan_job.py` + `test_config_defaults.py` — 147/147 pass (2.62s).
- Hermetic test coverage:
  - Source pin: `_process_candidate` contains `skipped_stale_tob` outcome.
  - Source pin: gate reads `TOB_STALE_MS` config knob (not a hard-coded literal).
  - Source pin: gate scoped to `metadata["entry_price_ts"]` (no global block).
  - Source pin: `late_entry_v3._evaluate_market` stamps `entry_price_ts`.
  - Default value: `Settings().TOB_STALE_MS == 2000`.
  - Env override: `TOB_STALE_MS=0` parsed correctly (disable sentinel).
  - Disable sentinel: gate code branches on `_tob_stale_ms > 0`.
  - Threshold math: strict `>` comparison — 2000ms is fresh, 2001ms is stale (parametrized over 11 boundary values).

**Behaviour in production (expected):**
- Normal scan→fill latency on Fly (sub-second per `_process_candidate` step timings recorded in prior lanes) → gate is dormant 99%+ of ticks.
- Back-pressured scheduler (executor busy, gate queue stretched) → previously-silent stale entries now surfaced as `scan_outcome=skipped_stale_tob` in structlog + telemetry skip counter. Operator gains visibility AND defensive rejection.
- signal_following, momentum, copy_trade candidates → unaffected (no `entry_price_ts` stamp; gate no-ops).

---

## 5. Known issues

- **Test environment dependencies.** Local `pytest` required installing `tenacity`, `sentry-sdk`, `apscheduler`, `PyJWT`, `pytest-asyncio`, `bcrypt`, `sse-starlette`, `uvicorn`, plus a `cryptography` upgrade. The crusaderbot `pyproject.toml` lists these; the repo-root `requirements.txt` is a stripped subset. CI installs from `pyproject.toml` so no impact there. Flagged as advisory only — out of scope for this lane.
- **Gate measures end-to-end latency, not pure orderbook age.** The stamp is taken when `_evaluate_market` builds the candidate (after CLOB `/book` fetch); the comparison happens at `_process_candidate` entry. The age therefore includes any queueing between scan and per-user candidate processing. This is intentional — the question we want to answer is "is the strategy's intended setup still live when we're about to buy?" — but a future lane could add a separate "ob_fetched_at" stamp for finer-grained observability.
- **No active stress test.** The gate is verified by source pins + threshold math, not by an integration test that artificially back-pressures the scheduler. Acceptable for MAJOR-NARROW; an integration harness for the scan→gate→executor path remains a deferred backlog item.

---

## 6. What is next

Per the WARP🔹CMD-approved 5-lane plan (Polybot directive synthesis):

| # | Lane | Tier | Status |
|---|---|---|---|
| 1 | `WARP/R00T/tob-freshness-gate` | MAJOR-NARROW | **THIS PR** — pending review |
| 2 | `WARP/R00T/close-sweep-spread-gate` | STANDARD-NARROW | queued |
| 3 | `WARP/R00T/complete-set-edge-metric` | MINOR-FOUNDATION | queued |
| 4 | `WARP/R00T/safe-close-direction-limit` | STANDARD-NARROW | queued |
| 5 | `WARP/R00T/bankroll-dynamic-sizing` | MAJOR-NARROW | queued |

Polybot directive items intentionally **declined** for this campaign:
- Dual-leg simultaneous YES+NO entry — fundamental conflict with multi-tenant directional architecture; would require an engine rewrite, not an improvement.
- Per-market inventory tracker — there is no bot-owned inventory; user positions are already tracked in the `positions` table.
- "AUTO_CASH polling wallet API with EMA smoothing" — bot is custodial; the internal ledger is the authoritative bankroll source, not on-chain RPC polls.
- Flip Hunter Mode B (directional contrarian with stop @ 0.15) — would revert PR #1415 Kreo-parity which WARP🔹CMD merged 2 days ago.

These declines are advisory findings, not actionable lanes. Documented here so the next reviewer doesn't re-litigate them.

---

## Validation declaration

```
Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : _process_candidate step 3b-0 (skipped_stale_tob) + late_entry_v3 entry_price_ts stamp + TOB_STALE_MS config knob
Not in Scope      : signal_following / momentum / copy_trade candidates; dual-leg arch; inventory tracker; bankroll dynamic sizing
Suggested Next    : WARP🔹CMD review
```
