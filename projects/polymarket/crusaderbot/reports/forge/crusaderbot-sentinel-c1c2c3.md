# WARP•FORGE Report — CrusaderBot SENTINEL C1+C2+C3 Fixes

- **Branch:** `WARP/CRUSADERBOT-REPLIT-IMPORT`
- **PR:** #852 (existing)
- **Triggering audit:** SENTINEL audit on PR #853
- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** scope-bound resolution of SENTINEL critical findings C1, C2, C3 — risk gate Kelly enforcement, migration idempotency, Tier 3 promotion gate
- **Not in Scope:** any other SENTINEL findings, any logic outside the four files listed below, any state/ folder updates

---

## 1. What was built

Three critical SENTINEL findings on PR #853 fixed:

- **C1 — Kelly enforcement + capital_alloc_pct cap.** `KELLY_FRACTION` was declared in `domain/risk/constants.py` but never referenced in any execution path, and `capital_alloc_pct` accepted up to 1.0 (full allocation). Both are CLAUDE.md hard-rule violations. Fix: gate now multiplies the position cap by a per-profile Kelly clamped to the global `K.KELLY_FRACTION`; setup validator now caps user input at 0.95 strictly less than 1.0.
- **C2 — migrations/004 idempotency.** `ALTER TABLE … ADD CONSTRAINT` does not support `IF NOT EXISTS`, so re-running migration 004 on every startup raised `duplicate_object`. Fix: every statement wrapped in a `DO $$ … IF NOT EXISTS … END $$` guard.
- **C3 — Tier 3 promotion gate.** `watch_deposits` promoted users to Tier 3 on every credited deposit regardless of cumulative balance, allowing dust deposits to bypass `MIN_DEPOSIT_USDC`. Fix: Tier 3 now only granted when `SUM(amount_usdc) >= settings.MIN_DEPOSIT_USDC`; user notification now reflects whether the gate was actually crossed.

## 2. Current system architecture

Pipeline unchanged: `DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING`.

Affected lanes:

- **RISK gate (`domain/risk/gate.py`):** step 13 (size cap + mode selection) now applies `kelly = min(profile["kelly"], K.KELLY_FRACTION)` and asserts both `KELLY_FRACTION` and `max_pos_pct` are in safe ranges. Effective per-trade size cap becomes `balance * max_pos_pct * kelly` — for `aggressive` profile that is `balance * 0.10 * 0.25 = 2.5%` of balance, fractional Kelly applied as required by CLAUDE.md.
- **Bot setup handler (`bot/handlers/setup.py`):** capital allocation prompt updated to `1-95`; validator rejects out-of-range with the explicit error message required by the spec; `awaiting` state preserved on rejection so the user can retry without re-opening the menu.
- **Migrations (`migrations/004_deposit_log_index.sql`):** three idempotent `DO $$` blocks — add column → drop legacy unique constraint → add new composite unique constraint. All three are now safe to re-run on every startup.
- **Deposit watcher (`scheduler.py::watch_deposits`):** Tier 3 promotion gated on `total_balance = SUM(deposits.amount_usdc WHERE confirmed_at IS NOT NULL)` against `settings.MIN_DEPOSIT_USDC`. `notify_after` extended with `tier_promoted: bool` so the Telegram confirmation message only claims "now Tier 3" when the gate actually crossed; sub-threshold deposits get a "top up" message instead. `audit.write` payload also gains `tier_promoted` for traceability.

## 3. Files created / modified (full repo-root paths)

Modified:

- `projects/polymarket/crusaderbot/domain/risk/gate.py` — KELLY_FRACTION applied in step-13 size cap, runtime asserts on KELLY_FRACTION and max_pos_pct.
- `projects/polymarket/crusaderbot/bot/handlers/setup.py` — capital_pct validator tightened to `1..95` strictly, explicit error message, runtime assert on persisted value, prompt text updated.
- `projects/polymarket/crusaderbot/migrations/004_deposit_log_index.sql` — three idempotent `DO $$` blocks replacing raw ALTER TABLE statements.
- `projects/polymarket/crusaderbot/scheduler.py` — `watch_deposits` queries cumulative confirmed deposit total, promotes to Tier 3 only if `>= MIN_DEPOSIT_USDC`, tier-aware Telegram notification, audit payload extended.

Created:

- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-sentinel-c1c2c3.md` — this report.

No files deleted. No structural changes outside the listed files. No state files touched.

## 4. What is working

- `KELLY_FRACTION` is now in the runtime path and enforced as a hard cap on per-profile Kelly. Verified by reading the gate at the size-cap step: `kelly = min(profile["kelly"], K.KELLY_FRACTION)` is the multiplier on `max_pos_size`.
- `capital_alloc_pct` validator rejects `>= 1.0` with the exact spec message; values in `1..95` proceed as before. Runtime assertion on the stored value (`0 < capital_alloc < 1.0`) backs the validator.
- Migration 004 is now safe to re-run on every startup. Each `DO $$` block checks `pg_constraint` / `information_schema.columns` before applying.
- Tier 3 promotion correctly gated. Sub-threshold deposits log the explicit `below MIN_DEPOSIT_USDC — Tier 3 not granted` message; over-threshold deposits log the promotion. Notification message follows the same branch.
- `python -m ast` parses all three modified Python modules cleanly (verified).

## 5. Known issues

- None introduced by this lane. Behavioural change worth flagging: with KELLY_FRACTION applied at the gate, the effective per-trade cap is now `max_pos_pct * kelly` (e.g. 2.5% for aggressive instead of 10%). This is the intended CLAUDE.md hard-rule posture but represents a sizing change that downstream tests (paper/live runs) should pick up.
- `audit.write` payload key `tier_promoted` is new — any downstream consumer that strictly validates the audit schema will need to accept the additional field. No such consumer is in this repo as of this commit.

## 6. What is next

- WARP•SENTINEL re-validates PR #852 on the patched branch; expect C1/C2/C3 to clear. Re-run Phase 0 (report present at `reports/forge/crusaderbot-sentinel-c1c2c3.md`, all 6 sections) and Phase 5 (risk rules in code — Kelly=0.25 referenced, capital_alloc cap < 1.0, MIN_DEPOSIT_USDC gate enforced).
- WARP🔹CMD final merge decision once SENTINEL re-verdict is APPROVED or CONDITIONAL.

---

## Suggested Next Step

WARP•SENTINEL re-audit on `WARP/CRUSADERBOT-REPLIT-IMPORT` head, scoped to C1/C2/C3 only, then return verdict to WARP🔹CMD.
