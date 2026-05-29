# WARP•R00T INCIDENT REPORT + FIX — candle-sync-observability

Branch: WARP/ROOT/candle-sync-observability
Date: 2026-05-30 03:20 Asia/Jakarta
Role: WARP•R00T (incident response, self-validated)

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : candle-market fetch failures are observable (WARNING + loud all-empty signal); /events poll volume reduced
Not in Scope      : the live runtime wedge itself (cleared by the redeploy this PR triggers); a full consecutive-empty operator-alert loop (follow-up)

## INCIDENT
Owner reported: bot not trading for hours on close_sweep / safe_close / flip_hunter
(all = the `late_entry_v3` candle strategy).

## ROOT CAUSE (evidence-backed, prod data + live Gamma)
The candle-market fetch (`integrations/polymarket.get_crypto_window_markets`,
called every ~15s by the `close_sweep_fast_scan` job and by `run_once`) returned
**empty for ~14h** while the scan loop kept running and reporting success.
- Last candle trade: `late_entry_v3` 2026-05-29 **05:44 UTC**.
- `markets` table: crypto `synced_at` frozen at **05:50:42 UTC**; 0 crypto rows
  synced in the following 6h+. Newest candle market = the 05:55–06:00 window.
- `scan_runs` (last 3h): `markets_seen=0`, `candidates=0` (strategies load fine).
- `close_sweep_fast_scan` ran **240×/hr continuously** 02:00→20:00 (no gap) — the
  loop never stopped; it just kept fetching 0 markets.
- Live Gamma check (during triage): `btc-updown-5m-<current slot>` **exists** —
  Polymarket still publishes these; slug format unchanged.
- Sentry: no errors → the failure was **silent**.

Conclusion: a runtime wedge in the bot's high-frequency Gamma `/events` candle
fetch starting ~05:50 UTC (consistent with a bot restart at that time; the
heavy 8-calls-per-15s `/events` polling is a plausible IP-throttle trigger,
while lower-volume `/markets` syncs kept working). NOT caused by the recent
audit campaign (candle trades stopped ~10h before its first deploy), NOT the
strategy toggles (`late_entry_v3` enabled), NOT Polymarket.

The defect that let a 14h primary-strategy outage pass unnoticed: the per-slug
fetch error was logged at **DEBUG** and the function returned `[]` silently, so
nothing surfaced to logs/Sentry/scan telemetry.

## FIX (this PR)
`integrations/polymarket.get_crypto_window_markets`:
1. Per-slug fetch exception now logs at **WARNING** (was debug) with slug + error
   — rate-limit/network failures become visible immediately.
2. New loud signal: if the whole candle universe returns empty AND every fetch
   errored (`fetch_errors>0`), log a WARNING summary (attempted/errors) — the
   exact condition that must page the operator, distinguished from a legitimately
   marketless gap (0 errors).
3. Cache TTL widened 20s → 45s (`_CRYPTO_WINDOW_CACHE_TTL`) to cut `/events` poll
   volume (~2.25x) — a hedge against the high-frequency polling that can get the
   bot IP throttled by Gamma. The market LIST is stable within a 5m window; entry
   timing (from `resolution_at`) is unaffected.

## REMEDIATION / SERVICE RESTORE
Merging this PR triggers the Fly CD redeploy, which **restarts the bot and clears
the runtime wedge → candle trading resumes**. The deployed code already fetches
correctly (it worked until 05:50; Gamma is live). Post-deploy verification:
confirm `markets` crypto `synced_at` advances and `late_entry_v3` positions
resume.

## Files
Modified: projects/polymarket/crusaderbot/integrations/polymarket.py
Created:  projects/polymarket/crusaderbot/tests/test_candle_sync_observability.py (4 tests)

## What is working
- py_compile + ruff clean; 4/4 hermetic tests pass (cache TTL, warning-not-debug
  source pin, all-error→empty, happy-path crypto-tagged markets).

## What is next
- Post-deploy: verify candle sync + trades resume (I will re-query prod).
- Follow-up (recommended): operator Telegram alert after N consecutive empty
  candle-universe ticks during market hours; confirm whether Gamma IP rate-limit
  is the trigger (now visible via the new WARNING logs).

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
