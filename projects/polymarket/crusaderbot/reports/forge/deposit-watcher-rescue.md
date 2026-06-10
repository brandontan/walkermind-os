# deposit-watcher-rescue — WARP•R00T incident root-cause + strategy audit lane

Branch: WARP/root-deposit-watcher-rescue
Role: WARP•R00T (owner-assigned)
Date: 2026-06-11 03:35 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : deposit watcher failure visibility + cold-start lookback; open-position dedup fail-closed in _process_candidate
Not in Scope      : Polygon RPC secret value (operator-owned), risk constants, execution/live gates, strategy entry-exit logic, migrations
Suggested Next    : operator sets a working POLYGON_RPC_URL (the escalated ERROR will name the exact exception in Sentry ~6 min after deploy), then deposit + backfill per activation sequence

## 1. What was built

Owner-reported: Enable Live Trading modal still blocked on gate 4 ("Wallet funded — at least one confirmed USDC deposit") + owner directive to audit the strategy layer.

INVESTIGATION (production data, Supabase): `deposits` table is EMPTY for ALL users; `wrong_token_deposits` empty; `chain_cursor` rows are still their migration seeds (`usdc_deposits`=0 seeded 2026-05-05 by migration 002, `usdc_native_deposits`=0 seeded 2026-06-08 by migration 093) with `updated_at` never touched by runtime. **The deposit watcher has never completed a single tick in production.** Every tick fails at `polygon.latest_block()` / `scan_from_cursor` and exits via a WARNING-level log that reaches neither Sentry nor any health surface — a 5-week-invisible outage. Gate 4 can never pass until this is fixed: even a correct USDC.e deposit to the right address is never seen. (Boot-validation from #1752 is live and already fired its own Sentry issue: 6 wallets have `polymarket_deposit_wallet` NULL — backfill not yet run.)

FIXES:
1. **Failure-streak escalation** (`scheduler._watch_deposits_failed`): consecutive watcher RPC failures escalate WARNING→ERROR (→ Sentry) at the 3rd failure and re-fire every 30th after, carrying `repr(exc)` + stage + streak. Success resets the streak. The next deploy surfaces the exact root exception within ~6 minutes (3 ticks × 120s) instead of staying invisible.
2. **Cold-start lookback** (`DEPOSIT_SCAN_LOOKBACK_BLOCKS`, default 50_000 ≈ 28h of Polygon blocks, env-tunable): `scan_from_cursor` previously hardcoded 2000 blocks (~70 min) when the cursor is 0 — a recovered watcher would have permanently missed any deposit sent during the outage. Threaded into both the USDC.e credit pass and the native-USDC wrong-token pass.
3. **Open-position dedup fails CLOSED** (`signal_scan_job._process_candidate` step 1b): the strategy audit's one verified-real finding. On a DB error in `_has_open_position_for_market` the code previously FELL THROUGH with a comment claiming "gate step 10 remains the safety net" — factually wrong: step 10 dedups on the (market, side, price, size) idempotency key, so a re-entry at a different price passes it and a transient DB blip could stack a second same-market position. Now: skip the candidate (telemetry reason `skipped_open_position_check_failed`), retry next tick.

STRATEGY AUDIT disposition (owner directive "pastikan strategy sesuai rules tanpa bug"): 10 rule groups audited. Kelly 0.25 clamp + ≤10% position (gate.py:654-663) ✓; per-user concurrent caps ✓; daily-loss/-drawdown/liquidity/kill-switch ✓ (incl. resume-path re-check); late_entry_v3 structural + oracle edge gate fail-open-by-design ✓; correlated-majors cap ✓; TP/SL bounds ✓; per-user timeframe ✓; complete-set 2% floor ✓; paper/live gate-before-execution ✓. Audit claims DISMISSED with evidence: "correlated-majors race" contradicts the #1725 sequential-processing proof (scheduler max_instances=1, candidates processed sequentially, in-memory record within the same loop); "engine exception bypasses gate" is fail-closed (an exception means NO trade executes — already logged at ERROR). The dedup fall-through (fix 3) was the single real defect.

## 2. Current system architecture (relevant slice)

- Deposit pipeline: `watch_deposits` (120s tick) → wallets watched-address set (EOA + safe + polymarket deposit wallet) → `polygon.scan_from_cursor` (cursor>0 ? cursor+1 : head−LOOKBACK, ≤1000 blocks/tick) → pending row → 32-block depth → confirmed + ledger credit → gate 4 reads `deposits.confirmed_at IS NOT NULL`. Failure now escalates after 3 consecutive misses.
- Catch-up: once the RPC works, the cursor advances 1000 blocks/tick (≈30k blocks/h); a 50k cold-start backlog clears in ~1.7h.
- Scan-loop dedup: step 1b open-position check is now fail-closed; gate step 10 idempotency unchanged.

## 3. Files created / modified

- projects/polymarket/crusaderbot/config.py — `DEPOSIT_SCAN_LOOKBACK_BLOCKS` (default 50_000)
- projects/polymarket/crusaderbot/scheduler.py — failure-streak escalation + lookback threading (both passes)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py — dedup fail-closed
- projects/polymarket/crusaderbot/tests/test_watch_deposits_rescue.py — 7 tests (NEW)
- projects/polymarket/crusaderbot/tests/test_signal_scan_job.py, test_fast_track_a.py, test_deposit_e2e.py — harnesses updated for the new contract (dedup stubbed healthy; fake_scan accepts lookback; fixture gains the new setting)
- projects/polymarket/crusaderbot/reports/forge/deposit-watcher-rescue.md — this report (NEW)
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md, state/CHANGELOG.md — state sync

## 4. What is working

- Full suite 3402 passed / 11 skipped (prior main baseline 3395/11). ruff clean on touched files.
- New tests pin: escalation at streak 3 + periodic re-fire (not per-tick spam), streak reset on success, lookback threaded with the configured value, config default, dedup DB-error → engine NEVER reached (fails on pre-fix code) + healthy-path positive control.

## 5. Known issues

- The WATCHER ROOT EXCEPTION itself is operator-environment (POLYGON_RPC_URL secret) and cannot be read from this session; the escalation makes it name itself in Sentry on the next deploy. Until a working RPC is set, gate 4 stays red.
- If the owner already sent a deposit MORE than ~28h before the watcher recovers, set `DEPOSIT_SCAN_LOOKBACK_BLOCKS` higher for one deploy (e.g. 500000 ≈ 11.5 days) so the rescue scan reaches it, then revert.
- 6 wallets still need `backfill_deposit_wallets()` (separate, already surfaced by the #1752 boot check in Sentry).

## 6. What is next

- Operator: verify/replace the `POLYGON_RPC_URL` Fly secret (Alchemy URL also accepted via `ALCHEMY_POLYGON_RPC_URL`); read the escalated Sentry error after deploy for the exact failure; then deposit USDC.e to the wallet address and watch gate 4 flip.
- Operator: run `backfill_deposit_wallets()` (per-user lane activation step a).
- No SENTINEL gate: WARP•R00T full-bypass merge per owner directive; invariants untouched.
