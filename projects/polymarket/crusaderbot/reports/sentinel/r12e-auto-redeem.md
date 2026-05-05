# R12e Auto-Redeem System — Sentinel Report

**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION (workers + queue wired end-to-end; on-chain CTF redemption tip gated by `EXECUTION_PATH_VALIDATED=false`)
**Source FORGE report:** projects/polymarket/crusaderbot/reports/forge/r12e-auto-redeem.md
**PR under audit:** #869 — WARP/CRUSADERBOT-R12E-AUTO-REDEEM @ c124aa843815
**Verdict:** APPROVED
**Score:** 92/100
**Critical Issues:** 0

---

## 1. Environment

- Env: `dev` (audit infra warn-only; risk rules ENFORCED)
- Mode: `paper` (default); live path gated by `EXECUTION_PATH_VALIDATED=False`
- Guards reviewed: `AUTO_REDEEM_ENABLED`, `EXECUTION_PATH_VALIDATED`, `INSTANT_REDEEM_GAS_GWEI_MAX`
- Audit scope (read-only): 8 files in services/redeem, migrations, bot, scheduler, tests
- Out of scope: state/docs files, full pipeline E2E run, live-tx submission

---

## 2. Test Plan

| Phase | Coverage |
|---|---|
| 0 | Pre-test: report path/sections, PROJECT_STATE.md update, no `phase*/` folders, hard-delete of inline R10 redeem |
| 1 | Functional per module: detection, classification, instant, hourly, reaper |
| 3 | Failure modes: Polymarket down, gas RPC down, settle raise, worker crash, audit.write raise |
| 4 | Async safety: claim atomicity, idempotent enqueue, two-tick re-detect, instant↔hourly race |
| 5 | Risk rules: 3-point activation guard, on-chain only on winners + EXECUTION_PATH_VALIDATED, double-credit prevention |
| 7 | Infra: migration 006 idempotency, indexes (pending, failed, processing) |
| 8 | Telegram: Settings UI callbacks + operator alert dispatch |

Phases 2 (pipeline E2E) and 6 (latency) inspected statically only; no runtime telemetry available in audit window.

---

## 3. Findings (per phase)

### Phase 0 — Pre-test (PASS)

- FORGE report at correct path, all 6 sections + 5 metadata fields present (`reports/forge/r12e-auto-redeem.md:1-160`).
- PROJECT_STATE.md updated: `Last Updated 2026-05-05 18:30 UTC`, R12e under [IN PROGRESS], NEXT PRIORITY points at SENTINEL audit (verified on PR branch via `git show`).
- No `phase*/` folders; legacy inline R10 redeem deleted from `scheduler.py` (only the 1-line delegations remain at `scheduler.py:365-382`).
- Migration 006 lives under `projects/polymarket/crusaderbot/migrations/` — matches the loader convention. Forge-flagged path deviation (task spec `infra/migrations/`) is correct: spec path would never run.

### Phase 1 — Functional (PASS)

- **Detection** (`redeem_router.py:45-91`): scans `positions × markets WHERE p.redeemed=FALSE AND m.resolved=FALSE`; per-market processing isolated in try/except. Correct.
- **Classification** (`redeem_router.py:94-178`): market flip is **deferred until classification finishes cleanly** (`classification_complete` flag drives the UPDATE at lines 162-168). On any per-position raise, the flag flips to False, the markets row stays `resolved=FALSE`, and the next tick re-runs. CORRECT — matches focus area #1.
- **Winner path** (`redeem_router.py:205-285`): closed-already branch flips `redeemed=TRUE` only; open branch runs `ensure_live_redemption` (live + EXECUTION_PATH_VALIDATED gated), credits ledger, marks position closed in a single transaction. Idempotent via `WHERE status='open' AND redeemed=FALSE RETURNING id`.
- **Loser path** (`redeem_router.py:288-342`): `pnl = -size_usdc` (mathematically equivalent to `-(shares × entry_price)`); no on-chain call; idempotent via same predicate. Matches focus area #9.
- **Instant worker** (`instant_worker.py:41-115`): claim → live-only gas guard → settle → mark_done; on raise, sleep 30s, retry once; on second raise, release with `increment_failure=True`. Matches focus area #3.
- **Hourly worker** (`hourly_worker.py:30-72`): reaper FIRST (`run_once:44-53`), then SELECT pending ORDER BY queued_at ASC, then per-row sequential drain with isolation. Matches focus area #4.
- **Reaper** (`redeem_router.py:447-479`): default `stale_after_seconds=300`, releases `processing→pending` without bumping `failure_count`. Matches focus area #7.

### Phase 3 — Failure modes (PASS)

| Failure | Behaviour | Evidence |
|---|---|---|
| Polymarket get_market raises | Caught at `redeem_router.py:89`; market stays `resolved=FALSE`; next tick retries | line 87-91 |
| Polygon gas RPC raises | `_gas_ok` returns False → release without increment | `instant_worker.py:124-129` |
| Polygon gas > threshold | Same release-without-increment path | `instant_worker.py:130-135` |
| Settle raises (instant 1st) | Logs warning, sleeps 30s, retries | `instant_worker.py:91-100` |
| Settle raises (instant 2nd) | Release with `increment_failure=True`; hourly will redrain | `instant_worker.py:102-115` |
| Settle raises (hourly) | Release + increment + alert if count≥2 | `hourly_worker.py:84-93` |
| Worker crash mid-process | Stale `processing` row reaped at +300s; no failure penalty | `redeem_router.py:447-479` |
| Reaper raises | Logged, drain still proceeds | `hourly_worker.py:51-53` (test `test_hourly_reap_failure_does_not_block_drain`) |
| Operator alert dispatch raises | Logged, does not propagate | `hourly_worker.py:114-120` |

### Phase 4 — Async safety (PASS)

- **claim_queue_row** (`redeem_router.py:396-434`): atomic `UPDATE ... WHERE status='pending' RETURNING id` inside a transaction. Status flip is the only synchronisation primitive — concurrent instant + hourly claim cannot both succeed.
- **Enqueue idempotency**: UNIQUE INDEX on `redeem_queue(position_id)` (`migrations/006:58-59`); enqueue uses `INSERT ... ON CONFLICT (position_id) DO NOTHING RETURNING id`.
- **Two-tick re-detect**: forge-flagged race window confirmed safe — markets UPDATE has `WHERE id=$1 AND resolved=FALSE`, loser settle has `WHERE status='open' AND redeemed=FALSE`, enqueue is ON CONFLICT idempotent.
- **LEFT JOIN user_settings + COALESCE('hourly')**: applied in BOTH the detection query (`redeem_router.py:130-141`) AND the claim query (`redeem_router.py:421-433`). Matches focus area #6 — missing settings rows route through hourly. Correct (an INNER JOIN here would silently drop positions for users without a settings row, stranding them forever after the markets flip).

### Phase 5 — Risk rules (PASS)

- **AUTO_REDEEM_ENABLED guard** at all 3 entry points (focus area #5):
  - `redeem_router.detect_resolutions` — line 65-68 (test `test_router_detect_short_circuits_when_disabled`)
  - `instant_worker.try_process` — line 48-52 (test `test_instant_worker_short_circuits_when_disabled`)
  - `hourly_worker.run_once` — line 39-42 (test `test_hourly_worker_short_circuits_when_disabled`)
  - All log INFO and return; no raise, no state mutation.
- **On-chain tip gating**: `ensure_live_redemption` (`redeem_router.py:345-391`) checks `s.EXECUTION_PATH_VALIDATED` at line 375 and returns early if False. Live engine falls back to internal-payout (claim level matches forge declaration).
- **Loser path on-chain inertia**: `settle_losing_position` does no chain call. Audit-traced; only DB UPDATE + `audit.write(action='redeem_loss')` + notification.
- **Winner double-credit prevention**: ledger credit is INSIDE the transaction with the position UPDATE (`redeem_router.py:256-274`); `WHERE status='open' AND redeemed=FALSE RETURNING id` returns None on retry, exiting before the credit.
- **Closed-already branch** (`redeem_router.py:228-243` for winners, `redeem_router.py:298-314` for losers): no double-credit (no ledger call); `WHERE redeemed=FALSE` guards the flag flip.

### Phase 7 — Infra (PASS)

- Migration 006 idempotency (focus area #8):
  - `CREATE TABLE IF NOT EXISTS redeem_queue` ✓ (line 36)
  - `claimed_at TIMESTAMPTZ` in CREATE ✓ (line 46)
  - Defensive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS claimed_at` for stale staging DBs ✓ (line 52-53)
  - `ON DELETE CASCADE` on user_id and position_id (line 38-39) — note: position deletion would also remove the queue row; matches FK cascade pattern in this codebase.
- Indexes:
  - `uq_redeem_queue_position` UNIQUE on `position_id` (line 58-59) — drives ON CONFLICT idempotency
  - `idx_redeem_queue_pending` partial on `status='pending'` (line 63-65) — keeps drain SELECT cheap
  - `idx_redeem_queue_failed` partial on `failure_count > 0` (line 68-70) — operator review
  - `idx_redeem_queue_processing` partial on `status='processing'` (line 76-78) — reaper scan
- `user_settings.auto_redeem_mode` defensive ADD COLUMN IF NOT EXISTS at line 84-85 — protects pre-006 staging DBs.

### Phase 8 — Telegram (PASS)

- Settings UI (`bot/handlers/settings.py`, `bot/keyboards/settings.py`): three callbacks (`settings:menu`, `settings:redeem`, `settings:redeem_set:<choice>`); choice validated against allow-list `{'instant','hourly'}` at line 85; no SQL on the callback path (uses `users.update_settings`).
- Operator alert (`hourly_worker.py:96-120`): body includes queue_id / position_id / user_id / market_id / side / mode / failures / last_error[:300]. Cooldown key = `str(queue_id)`, alert_type = `redeem_failed_persistent` — distinct from `close_failed_persistent` so the two paths do not collide.
- `alerts._dispatch` signature `(alert_type, key, body)` matches usage (`monitoring/alerts.py:63`).

---

## 4. Critical Issues

**None found.**

---

## 5. Stability Score

| Category | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 19 | services/redeem owns settlement; scheduler thin (1-line delegations); workers thin; -1 for `auto_redeem_mode` cruft in claim SELECT (unused by workers). |
| Functional | 20 | 18 | Classification + idempotency + transactional credit all correct; -2 for outcome-fallback edge (`outcomes = m.get("outcomePrices") or [0.5, 0.5]` arbitrarily picks "no" winner if API returns null on a closed market). |
| Failure modes | 20 | 18 | Reaper, gas guard, retry-once, isolation all wired; -2 for audit.write/notify outside the settle transaction (idempotency check on retry skips the audit if it fails post-commit — minor traceability gap, not a correctness issue). |
| Risk rules | 20 | 19 | All 3 activation guard points correct, EXECUTION_PATH_VALIDATED gates live-tx tip, no on-chain side-effect on losers, double-credit blocked by transactional WHERE clause; -1 for `AUTO_REDEEM_ENABLED` defaulting to True (R10 inheritance — task spec called for False; flagged in forge "Known Issues"). |
| Infra + Telegram | 10 | 10 | Migration idempotent + 4 indexes correctly partialled; alerts dispatch + cooldown key clean; Settings UI choice allow-listed. |
| Latency | 10 | 8 | Static review only — no runtime telemetry in audit window; intervals (300s detect / 3600s drain / 30s instant retry / 300s reaper) consistent and safe. |
| **TOTAL** | **100** | **92** | |

---

## 6. GO-LIVE Status

**Verdict: APPROVED**

- Score 92 ≥ 85 threshold
- Zero critical issues
- All 9 audit focus points verified PASS:
  1. Resolution detection — market flip deferred until classification done ✓ (`redeem_router.py:162-173`)
  2. Winner/loser classification — WIN→queue, LOSE→settle at ≤$0 ✓
  3. Instant worker — gas guard / retry-once / defer ✓
  4. Hourly worker — reaper first / sequential drain / alert at ≥2 ✓
  5. AUTO_REDEEM_ENABLED guard — all 3 entry points short-circuit ✓
  6. LEFT JOIN user_settings + COALESCE 'hourly' ✓
  7. claimed_at reaper — 300s, no failure bump ✓
  8. Migration 006 — idempotent, indexes, claimed_at column ✓
  9. Loser settlement — `pnl=-size_usdc`, no on-chain tx ✓

NARROW INTEGRATION claim is sound: workers + queue wired end-to-end; the `polymarket.submit_live_redemption` tip remains gated by `config.EXECUTION_PATH_VALIDATED=False`, so this lane does not by itself enable live on-chain redemption. WARP🔹CMD merge-decision can proceed.

---

## 7. Fix Recommendations (priority ordered)

All recommendations are NON-BLOCKING. Verdict stands as APPROVED.

### Priority 2 — Pre-live (before flipping `EXECUTION_PATH_VALIDATED`)

1. **Tighten outcome-detection fallback** (`redeem_router.py:114-116`):
   - Current: `outcomes = m.get("outcomePrices") or [0.5, 0.5]` followed by `winning = "yes" if yes_price > 0.5 else "no"` arbitrarily routes a malformed-API closed market into the "no" winner branch.
   - Suggested: if `outcomePrices` is missing on a `closed` market, log WARN and skip (return without flipping `markets.resolved`); the next tick will retry once Polymarket returns prices.

2. **Move audit.write inside the settle transaction or guard with idempotency token** (`redeem_router.py:276-285`, `333-338`):
   - Current: position UPDATE + ledger credit are transactional; audit.write + notify run outside.
   - If audit.write raises post-commit, the position is settled but the audit row is missing, and the retry-path predicate (`WHERE status='open' AND redeemed=FALSE`) skips the audit too.
   - Suggested: either move `audit.write` inside the transaction (preferred — same pool, same conn), or persist a queue-row `audit_written_at` flag so the retry path can re-emit cleanly.

### Priority 3 — Hygiene / follow-up

3. **Decide `AUTO_REDEEM_ENABLED` default policy** (`config.py:92`):
   - Forge report flagged this. Default is currently `True` (R10 inheritance); R12e task spec body suggested `False`. Either flip to False for safer paper-only default, or document the True default as the new agreed posture in CLAUDE.md / blueprint.

4. **Drop unused `auto_redeem_mode` from `claim_queue_row` SELECT** (`redeem_router.py:425`):
   - Selected via `COALESCE(us.auto_redeem_mode, 'hourly')` but neither worker reads the field after claim. Cruft — harmless but should be removed for clarity, or used (e.g., to log which mode pulled the row).

5. **Expose a public `alert_operator_redeem_failed_persistent` wrapper** (`monitoring/alerts.py`):
   - Forge report flagged this. Hourly worker calls `alerts._dispatch` directly. A typed public helper matches the `close_failed_persistent` pattern at `alerts.py:427` and removes the underscore-prefix smell.

6. **Document the `ON DELETE CASCADE` choice on `redeem_queue`** (`migrations/006_redeem_queue.sql:38-39`):
   - Deleting a `users` or `positions` row drops the queue row silently. Matches the FK-cascade convention in this codebase but worth a one-line comment in the migration so a future operator does not lose the audit trail by accident.

7. **Consider gating instant-mode dispatch when `mode='live'` and `EXECUTION_PATH_VALIDATED=False`**:
   - Today the instant fast-path runs for live-mode positions even when on-chain submission is gated; it succeeds on the internal-payout path but the gas guard still fires. Either log INFO (gas check skipped — chain tip gated) or short-circuit straight to the hourly path. Cosmetic only; behaviour is correct.

---

## 8. Telegram Preview

### Settings menu (user-facing)

```
⚙️ Settings

Auto-Redeem Mode: hourly

_Instant uses more gas. Hourly batches redeems for lower cost._

[ 🏆 Auto-Redeem Mode: Hourly ]   ← settings:redeem
```

Picker after tap:

```
Pick auto-redeem mode.

*Instant* — settle the moment a market resolves
(live trades are gas-spike guarded).
*Hourly* — wait for the hourly batch (default, lower gas).

[ ◻️ Instant ]   ← settings:redeem_set:instant
[ ✅ Hourly  ]   ← settings:redeem_set:hourly
[ ⬅️ Back    ]   ← settings:menu
```

Confirmation:

```
✅ Auto-redeem mode set to *instant*.
```

### User notifications

Winner:

```
🏆 *Redeemed* — winning side `yes`
Payoff: *$+150.00*
```

Loser:

```
❌ *Market resolved* — your position closed at a loss.
Side: `no` · P&L: *$-100.00*
```

### Operator alert (>= 2 consecutive failures)

```
[CrusaderBot] persistent redeem failure
queue: <queue_uuid>
position: <position_uuid>
user: <user_uuid>
market: <market_id>
side: yes
mode: live
failures: 2
last_error: <stack-fragment-trimmed-to-300-chars>
```

Cooldown key: `redeem_failed_persistent:<queue_uuid>` — collision-free vs `close_failed_persistent` (different alert_type) and per-row dimensioned.

---

## 9. Procedural Notes

- Audit dev branch is `claude/audit-auto-redeem-ZuBH4` (system-assigned). CLAUDE.md HARD RULE forbids `claude/...` branch names; flagged here for WARP🔹CMD awareness — does not affect the audit verdict on PR #869 (`WARP/CRUSADERBOT-R12E-AUTO-REDEEM`), which is correctly named.
- No tests run by SENTINEL per task instructions — findings are static-analysis + cross-reference only. Forge report claims 14/14 redeem tests + 87/87 full suite passing.
- This audit did not run pipeline E2E nor measure latency; both are static-only conclusions based on code paths and configured intervals.

