# WARP•ROOT — bankroll-cb-persistence (B1 hardening — DESIGN SPEC)

Role: WARP•R00T
Branch: WARP/ROOT/bankroll-cb-persistence
Date: 2026-05-31 Asia/Jakarta
Validation Tier: MAJOR (bankroll circuit breaker — risk path) → WARP•SENTINEL on implementation
Claim Level: FOUNDATION (design spec — no runtime code in this lane)
Validation Target: persistence/restart-durability of the bankroll circuit breaker state (audit F19/F4)
Not in Scope: ENABLING the breaker (`BANKROLL_CIRCUIT_BREAKER_ENABLED` stays FALSE — owner's directive validate track); the always-on 8% drawdown halt (gate step 6, unchanged)
Posture: the entire breaker path is gated behind `BANKROLL_CIRCUIT_BREAKER_ENABLED=false` (services/signal_scan/signal_scan_job.py:1606), so all code proposed here is **DARK** — zero production runtime effect until the owner flips the flag under the validate track.

## 1. What was built

Lane opened with a build-ready design spec (no runtime code committed yet — see §6 for why this risk-path build is staged rather than rushed). This spec closes audit finding **F19/F4**: the circuit breaker's state is in-process only and does not survive a restart.

## 2. Current system architecture (the gap)

The breaker keeps two per-user maps **in memory**: `_bankroll_circuit_baseline` (peak high-water, ratcheted up by `_update_bankroll_baseline`, signal_scan_job.py:313-321) and `_bankroll_circuit_tripped` (the hysteresis latch). A reserved write point already exists: `_bankroll_circuit_baseline_persist_hook(uid)` (signal_scan_job.py:1620). On every redeploy/restart (e.g. the 4 CD deploys just shipped) both maps reset, causing two failures **once the breaker is enabled**:

- **F19-a (worst): a TRIPPED breaker silently un-trips on restart** → NEW entries re-open for a user who was halted for drawdown, until the threshold re-trips on the next tick. A halt that a redeploy cancels is a real money-safety regression.
- **F19-b: the peak baseline resets to the current (possibly drawn-down) balance** → future drawdown is measured from a depressed reference, so the breaker trips later (or not at all) than intended.

## 3. Files created/modified

- Created (this lane): `projects/polymarket/crusaderbot/reports/forge/bankroll-cb-persistence.md` (this spec).
- Planned (implementation lane — see §6):
  - `infra/migrations/0NN_bankroll_circuit_state.sql` — additive `CREATE TABLE bankroll_circuit_state(user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, baseline NUMERIC NOT NULL, tripped BOOLEAN NOT NULL DEFAULT false, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())` + RLS deny-by-default (match the 43/43 RLS posture). FK + `ON DELETE CASCADE` keeps state referentially clean and auto-reaps rows when a user is deleted (per CodeRabbit/Gemini review).
  - `services/signal_scan/signal_scan_job.py` — implement `_bankroll_circuit_baseline_persist_hook` (UPSERT baseline+tripped); add `_restore_bankroll_circuit_state()` (load all rows → in-memory maps) called once at scan-job start; write the latch on trip AND on hysteresis-resume.
  - `tests/test_bankroll_circuit_persistence.py` — hermetic.

## 4. What is working

Nothing runtime yet (spec only). The existing breaker logic + the always-on 8% drawdown halt (gate step 6) are unchanged. The hook insertion point (signal_scan_job.py:1620) and the flag gate (1606) already exist, so the implementation is a contained completion, not a refactor.

## 5. Known issues

- Until implemented + enabled, F19 stands: a redeploy during an active (enabled) breaker halt would un-trip it. Mitigated today ONLY because the breaker is OFF (dark) — so there is no live halt to lose.
- Storage choice: a dedicated table (proposed) vs a JSONB column on `user_settings`. Table chosen for clean RLS + indexable `updated_at` retention; SENTINEL to confirm.

## 6. What is next (implementation contract for the validate track)

Implementation steps, each behind the OFF flag (dark) so prod is untouched until enablement:
1. Migration (additive table + RLS). Applied by owner; an unused table is inert.
2. `_restore_bankroll_circuit_state()` at scan start, **gated on `BANKROLL_CIRCUIT_BREAKER_ENABLED`** (no restore work when off).
3. Persist on every state change: baseline ratchet (via the existing hook), trip, and resume.
4. Cold-start seed: `baseline = max(current_balance, COALESCE(peak_from_portfolio_snapshots, 0))` — handle `None`/`NULL` defensively (no snapshots → fall back to `current_balance`; never `max(x, None)` which raises `TypeError`) so a first-ever start still measures from a real peak.
5. Fail-OPEN on any persistence error (match the existing breaker contract at signal_scan_job.py:1622-1625 — a persistence bug must never halt every user).
6. Hermetic tests: persist→restore round-trip; tripped latch survives a simulated restart; baseline ratchet-up only; resume clears the latch + persists; fail-open on DB error; **no-op when flag is OFF** (dark pin).

**Why staged, not hot-built:** this is MAJOR trading-risk-path code touching DB persistence. Per the HARD FENCE and money-bot caution, it should be built as a focused effort with full hermetic coverage and a WARP•SENTINEL pass, then validated on the directive track (unit → 7d paper → 7d live-25% → 100%) alongside flipping `BANKROLL_CIRCUIT_BREAKER_ENABLED`. This spec makes that build a mechanical, low-ambiguity task.

Suggested Next Step: WARP🔹CMD authorizes the implementation lane (I can execute it directly from this spec); SENTINEL validates; then enable the breaker under the validate track.
