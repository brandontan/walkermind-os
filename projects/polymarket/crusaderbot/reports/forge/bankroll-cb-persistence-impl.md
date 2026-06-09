# WARP•ROOT — bankroll-cb-persistence-impl

Role: WARP•R00T
Branch: WARP/ROOT/bankroll-cb-persistence-impl
Date: 2026-05-31 Asia/Jakarta
Validation Tier: MAJOR (bankroll circuit breaker — trading-risk path; touches DB persistence) → WARP•SENTINEL required before merge
Claim Level: NARROW INTEGRATION
Validation Target: restart-durable persistence of the bankroll circuit-breaker baseline + tripped latch
Not in Scope: ENABLING the breaker (`BANKROLL_CIRCUIT_BREAKER_ENABLED` stays FALSE — owner's directive validate track); changing trip/resume math; the always-on 8% drawdown halt (gate step 6, unchanged)
Implements: WARP/ROOT/bankroll-cb-persistence design spec (PR #1503, merged); closes audit F19/F4

## 1. What was built

Restart-durable persistence for the bankroll circuit breaker. The breaker's per-user baseline (peak reference) and tripped latch lived only in process memory, so every restart/redeploy wiped them — a TRIPPED breaker would silently un-trip and the peak baseline would reset to the current (possibly drawn-down) balance (audit F19/F4). This lane persists both to a new `bankroll_circuit_state` table and restores them at scan-job start.

DARK: every new path is gated on `BANKROLL_CIRCUIT_BREAKER_ENABLED` (default FALSE). With the flag off, `run_once` does zero extra DB work and the gate never persists — deploying this is a true no-op vs current behaviour until the owner enables the breaker under the validate track.

## 2. Current system architecture

- New table `bankroll_circuit_state(user_id PK→users.id ON DELETE CASCADE, baseline NUMERIC, tripped BOOL, updated_at)` — additive, deny-by-default RLS (migration 073), matching the 43/43 RLS posture.
- `_restore_bankroll_circuit_state()` (async): one `SELECT` → seeds the in-memory `_bankroll_ema_baseline` / `_bankroll_circuit_tripped` dicts. Idempotent — only fills keys not already warmed this process, so it never clobbers fresher in-process state. Skips non-finite / ≤0 baselines defensively.
- `_persist_bankroll_circuit_state(user_id)` (async): `INSERT … ON CONFLICT (user_id) DO UPDATE` of baseline+tripped.
- Wiring: `run_once` calls restore once per tick, flag-gated (no-op when dark). The circuit-breaker gate in `_process_candidate` calls persist immediately after `_evaluate_bankroll_circuit_breaker`, so BOTH the trip and the hysteresis-resume transitions are written.
- FAIL-OPEN throughout: any DB error in restore/persist is logged at WARNING and swallowed — a persistence fault can never halt the scan or lock users out (mirrors the breaker's existing fail-open config-read contract).

## 3. Files created/modified

- Created: `projects/polymarket/crusaderbot/migrations/073_bankroll_circuit_state.sql` (table + RLS).
- Modified: `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (+`_restore_bankroll_circuit_state`, +`_persist_bankroll_circuit_state`; restore wired into `run_once` flag-gated; persist wired into the CB gate).
- Created: `projects/polymarket/crusaderbot/tests/test_bankroll_circuit_persistence.py` (12 hermetic tests).
- Created: `projects/polymarket/crusaderbot/reports/forge/bankroll-cb-persistence-impl.md` (this report).
- Modified (state): `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md`.

## 4. What is working

- 12/12 new tests pass: persist UPSERT shape+values (trip + resume), restore round-trip, **tripped latch survives a simulated restart** (the core F19 regression), restored baseline = persisted peak (not drawn-down balance), restore does-not-clobber-warmed-state, fail-open on persist/restore DB error, invalid-baseline rows skipped, empty-table no-op, + 2 source pins (restore is flag-gated in `run_once`; gate persists after evaluate).
- No regression: `test_signal_scan_job.py` 74/74 pass.
- `ruff check` + `py_compile` clean on the modified source, the new test, and (compile) the rest.

## 5. Known issues

- Cold-start seed from the all-time `portfolio_snapshots` peak (spec step 4) is intentionally NOT included here: the breaker already seeds the baseline to the current balance on first observation (`_ensure_bankroll_baseline_seeded`), and after this lane that seed persists immediately — so the peak ratchets forward from first enablement. A historical-peak backfill is a small optional follow-up (`WARP/ROOT/bankroll-cb-coldstart-seed`) and is not required for restart-durability. Flagged, not silently dropped.
- Migration 073 must be applied to Supabase before enabling the flag (an unused table is inert; restore fail-opens if the table is absent).

## 6. What is next

WARP•SENTINEL validation (MAJOR — trading-risk path + DB). Then WARP🔹CMD merge decision. After merge + migration applied, the breaker (with B1 now restart-durable) can be enabled via the directive validate track (unit → 7d paper → 7d live-25% → 100%).

Suggested Next Step: WARP•SENTINEL pass on this lane; apply migration 073; then the owner's CB-enablement track.
