# WARP•FORGE Report — Late Entry V3 final-~35s window + dedicated fast scan

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: Late Entry V3 entry-window narrowing (240s -> 35s) and the new dedicated high-frequency close_sweep scan loop that makes the narrow window reliably catchable.
- Not in Scope: risk gate / sizing (unchanged); other strategies' cadence (still 180s); the auto-redeem flag (separate lane).
- Suggested Next Step: WARP•SENTINEL validation, then Fly redeploy + confirm Close Sweep enters only in the final ~35s.

---

## 1. What was built

Owner observation (screenshot of a reference Close Sweep config): the proven edge enters
in the FINAL ~35s of a candle (5m `Time: 265-299s`, 15m `865-899s`), not 4 minutes out.
Late Entry V3 was using a 240s window, which enters far too early.

Two coupled changes:
1. `ENTRY_WINDOW_SEC` 240 -> 35 in `late_entry_v3.py` — enter only when
   `0 < seconds_to_close <= 35`.
2. New dedicated scan loop `signal_scan_job.run_close_sweep_fast()` scheduled every
   `CLOSE_SWEEP_SCAN_INTERVAL` (15s). The main scan runs every 180s and would step
   over a 35s window, so a tight window alone would rarely fire. The fast loop scans
   ONLY `close_sweep` users with ONLY the `late_entry_v3` domain strategy.

## 2. Current system architecture

`scheduler.setup_scheduler` now registers `close_sweep_fast_scan`
(`sf_scan_job.run_close_sweep_fast`, interval `CLOSE_SWEEP_SCAN_INTERVAL`=15s,
max_instances=1, coalesce). The fast loop:
- loads enrolled users (`_load_enrolled_users`), keeps only `active_preset=='close_sweep'`;
- upserts the live candle window (`get_crypto_window_markets` + `_upsert_crypto_window_markets`)
  so `_process_candidate._load_market` resolves;
- runs `late_entry_v3.scan` and routes candidates through the existing `_process_candidate`
  (full risk gate + paper execution).

It writes NO `scan_runs` row (in-memory `ScanTelemetry`) to avoid flooding the table at
15s cadence. `_process_candidate` idempotency + open-position dedup make the overlap with
`run_once`'s Phase-B2 (which still serves full_auto/None users) harmless. API load is
bounded by existing caches (`get_crypto_window_markets` 20s, `get_book` 30s).

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py (window 240->35)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py (run_close_sweep_fast + __all__)
- projects/polymarket/crusaderbot/config.py (CLOSE_SWEEP_SCAN_INTERVAL=15)
- projects/polymarket/crusaderbot/scheduler.py (close_sweep_fast_scan job)
- projects/polymarket/crusaderbot/tests/test_late_entry_v3.py (default window fixture 20s)
- projects/polymarket/crusaderbot/tests/test_signal_scan_job.py (+3 run_close_sweep_fast tests)
- projects/polymarket/crusaderbot/tests/test_daily_pnl_summary.py / test_lifecycle_ws.py / test_order_lifecycle.py (fake settings gain CLOSE_SWEEP_SCAN_INTERVAL)

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- Full suite: 1743 passed, 1 skipped. py_compile clean.
- New tests: run_close_sweep_fast scans only close_sweep users, no-ops when none, and
  returns early when late_entry_v3 is unregistered; late_entry entry-window tests updated
  to the 35s gate (enter at 20s, skip at 120s/600s).

## 5. Known issues

- 15s cadence is a tradeoff; mostly cache reads between the 20s/30s cache expiries, so
  Gamma/CLOB load stays bounded. Can be tuned via CLOSE_SWEEP_SCAN_INTERVAL.
- close_sweep users are scanned by BOTH the fast loop and run_once Phase-B2 (every 180s);
  dedup makes this safe but slightly redundant — left for simplicity.
- Settlement still depends on the auto-redeem flag (separate lane WARP-ARE) being enabled.

## 6. What is next

- WARP•SENTINEL validation, then Fly redeploy.
- Confirm via Supabase MCP (project ykyagjdeqcgcktnpdhes): new late_entry_v3 positions
  open with `seconds_to_close <= 35` (check metadata / open vs candle resolution_at), and
  the close_sweep_fast_scan job ticks every ~15s.
