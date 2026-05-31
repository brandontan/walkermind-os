# WARP•SENTINEL — bankroll-cb-persistence-impl

Role: WARP•SENTINEL
Branch validated: WARP/ROOT/bankroll-cb-persistence-impl (+ #1505 + #1506 hardening)
Date: 2026-05-31 Asia/Jakarta
Validation Tier: MAJOR (trading-risk path + DB persistence)
Claim Level: NARROW INTEGRATION
Validation Target: Restart-durable persistence of the bankroll circuit-breaker baseline and tripped latch (audit F19/F4)
Not in Scope: Enabling the breaker (BANKROLL_CIRCUIT_BREAKER_ENABLED stays FALSE), trip/resume math, the always-on 8% drawdown halt, application migrations to Supabase

---

## TEST PLAN

Environment: dev (warn-only infra; risk ENFORCED; no Telegram dependency in this lane)
Scope: signal_scan_job persistence functions + wiring + migrations + hermetic suite
Phases run: 0 (pre-test), 1 (functional), 2 (pipeline), 3 (failure modes), 4 (async safety), 5 (risk rules), 6 (latency), 7 (infra), 8 (Telegram — N/A this lane)

---

## FINDINGS

### Phase 0 — Pre-Test

- Forge report present at correct path: `projects/polymarket/crusaderbot/reports/forge/bankroll-cb-persistence-impl.md` — all 6 sections, correct naming. PASS
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` Last Updated 2026-05-31 11:55 WIB. PASS
- No `phase*/` folders in repo. PASS
- Implementation evidence present (3 new functions + 2 wiring sites + 2 migrations + 12 tests). PASS

### Phase 1 — Functional Testing

**`_restore_bankroll_circuit_state` (signal_scan_job.py:405)**

- SELECT `user_id, baseline, tripped` from `bankroll_circuit_state`. PASS
- Float coercion on `baseline` — TypeError/ValueError → `continue` (row skipped). PASS
- `baseline > 0` and `math.isfinite(baseline)` guard — non-positive/non-finite rows skipped. PASS
- Idempotency: only writes keys not already in `_bankroll_ema_baseline` / `_bankroll_circuit_tripped`. PASS
- Restores `_bankroll_ema_baseline_active` and `_bankroll_ema_last_update` alongside the primary dict. PASS
- Empty table: loop body never executes, dicts stay empty. PASS

**`_persist_bankroll_circuit_state` (signal_scan_job.py:446)**

- Baseline guard at line 456: returns early when baseline is None / non-positive / non-finite (no DB call). PASS
- SQL: `INSERT INTO bankroll_circuit_state (user_id, baseline, tripped, updated_at) VALUES ($1::uuid, $2, $3, now()) ON CONFLICT (user_id) DO UPDATE SET baseline = EXCLUDED.baseline, tripped = EXCLUDED.tripped, updated_at = now()`. PASS
- `$1::uuid` cast present (verified via `assert "$1::uuid" in sql` in test). PASS
- tripped defaulted False when key absent. PASS

**Restore wiring in `run_once` (signal_scan_job.py:2519)**

- Independent `_get_settings()` call (not reusing `_s` which may be unbound on config-read failure). PASS
- `if _cb_on:` guard — zero DB work when BANKROLL_CIRCUIT_BREAKER_ENABLED=False. PASS
- Double try/except: outer catches config-read failure; inner `_restore_bankroll_circuit_state` has its own except. PASS

**Persist wiring in `_process_candidate` — site 1 (signal_scan_job.py:1760)**

- `_uid_str` and `_prev_baseline` / `_prev_tripped` captured BEFORE `_ensure_bankroll_baseline_seeded` (#1506 fix). PASS
- First-ever seed (None → value) correctly detected as transition → persist fires. PASS
- EMA not modified by `_evaluate_bankroll_circuit_breaker` → baseline comparison reflects only seeding. PASS
- Trip (`False → True`) and resume (`True → False`) both trigger persist. PASS
- No-change case (steady state): `_new_baseline == _prev_baseline` and `_new_tripped == _prev_tripped` → no DB call. PASS

**Persist wiring in `_process_candidate` — site 2 (signal_scan_job.py:2322)**

- `_base_before_build` captured before `_build_trade_signal`. PASS
- `_bankroll_multiplier` (inside `_build_trade_signal`) may advance `_bankroll_ema_baseline` via EMA. PASS
- After build: if baseline changed, persist fires (#1506 fix). PASS
- Guard: `if _cb_enabled and ... != _base_before_build` — zero work when CB off. PASS

### Phase 2 — Pipeline End-to-End

- Crash-recovery (step 0, line 1645) executes BEFORE CB gate (line 1737+). In-flight approved trades always complete. PASS
- CB gate is step 0a — after crash-recovery, before dedup (step 1), before engine.execute (step 4). PASS
- `if _cb_tripped: return` fires BEFORE `_engine.execute` — a tripped breaker blocks new entries, not completions. PASS
- Both trip AND resume transitions write to DB (trip flips `_new_tripped = True`; resume flips back). PASS

### Phase 3 — Failure Modes

- Restore DB error: `except Exception → logger.warning("bankroll_circuit_restore_failed") → return`. Dicts stay empty. Scan proceeds normally. PASS
- Persist DB error: `except Exception → logger.warning("bankroll_circuit_persist_failed")`. No re-raise. In-memory latch still governs. PASS
- Config-read failure at restore gate: `except Exception → logger.warning("bankroll_circuit_restore_gate_failed")`. `_cb_on` never set. No DB call. PASS
- Invalid restore rows (baseline=0, baseline=None): skipped at `if not math.isfinite(baseline) or baseline <= 0`. PASS
- Non-positive/non-finite balance in persist: `if baseline is None or not math.isfinite(baseline) or baseline <= 0: return` — no DB call. PASS
- Pool unavailable: `get_pool()` may raise; caught by the outer except in both functions. PASS

### Phase 4 — Async Safety

- All DB operations inside `async with pool.acquire() as conn:`. No blocking I/O. PASS
- No `threading` anywhere in this lane. PASS
- Dict ops (`_bankroll_ema_baseline.get`, `.clear`) — CPython GIL-safe for single-key access. PASS
- `asyncio.run` never called inside async context. PASS

### Phase 5 — Risk Rules

- Kelly=0.25 cap: gate.py unchanged. PASS
- CB gate fires at step 0a, BEFORE `_engine.execute` (step 4). A tripped user never reaches the risk gate. PASS
- ENABLE_LIVE_TRADING guard: untouched. PASS
- Per-user kill switch / pause: untouched. PASS
- No risk rule weakened or bypassed by this lane. PASS

### Phase 6 — Latency

- `_restore_bankroll_circuit_state`: called once per `run_once` tick (not per candidate). One SELECT across all users. PASS
- `_persist_bankroll_circuit_state`: called only on state transition. Steady-state candidates (no seed/trip/resume) skip entirely. PASS
- EMA ratchet check at site 2: two dict lookups + conditional — negligible overhead. PASS

### Phase 7 — Infra

- Migration 073 (`bankroll_circuit_state`): `user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE`, `baseline NUMERIC NOT NULL`, `tripped BOOLEAN NOT NULL DEFAULT FALSE`, `updated_at TIMESTAMPTZ`. RLS ENABLED (deny-by-default, no policy — anon blocked). PASS
- Migration 074: defensive `DELETE FROM bankroll_circuit_state WHERE baseline IS NULL OR baseline <= 0` + `ADD CONSTRAINT bankroll_circuit_state_baseline_positive CHECK (baseline > 0)`. PASS
- `NOT NULL` on baseline column (migration 073) makes the `IS NOT NULL` clause in CHECK redundant — `CHECK (baseline > 0)` suffices. PASS
- **NOT YET APPLIED to Supabase** — table does not exist in production. `_restore_bankroll_circuit_state` will fail-open (`relation "bankroll_circuit_state" does not exist`) and log WARNING. Safe until flag is enabled. CONDITIONAL ⚠️

### Phase 8 — Telegram

Not in scope for this lane. No Telegram code modified. PASS

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

| Category | Weight | Score | Notes |
|----------|--------|-------|-------|
| Architecture | 20% | 20/20 | Three layers clean (restore/persist/wiring). Idempotent. Fail-open at all call sites. Dark-launch enforced. |
| Functional | 20% | 18/20 | All functions correct. Seed-order + EMA ratchet fixes verified in code. No dedicated tests for the two #1506 wiring fixes (behavioral coverage via existing suite is strong, but direct test pins are absent). |
| Failure modes | 20% | 20/20 | Every error path logged + swallowed. 4/4 fail-open tests pass. Invalid-row defensive skip. |
| Risk rules | 20% | 20/20 | CB gate before engine.execute. Crash-recovery ordering correct. No risk bypass. |
| Infra + Telegram | 10% | 7/10 | Migrations 073+074 exist and are correct. RLS deny-by-default. NOT applied to Supabase yet — required before enabling flag. |
| Latency | 10% | 10/10 | Restore once per tick. Persist only on transition. Zero overhead when CB dark. |
| **TOTAL** | 100% | **95/100** | |

---

## GO-LIVE STATUS

**VERDICT: APPROVED (conditional)**
**Score: 95/100**
**Critical issues: 0**

Condition: Apply migrations 073 + 074 to Supabase before setting `BANKROLL_CIRCUIT_BREAKER_ENABLED=true`. The table is inert until the flag is enabled, so the undeployed migration is safe-by-default (restore fails-open; persist never fires).

Enable sequence (per directive validate track):
1. Apply migration 073 to Supabase
2. Apply migration 074 to Supabase
3. Set `BANKROLL_CIRCUIT_BREAKER_ENABLED=true` in Fly secrets
4. Observe 7d paper — confirm no spurious trips, confirm persisted state survives deploys
5. 7d live-25% → live-100%

---

## FIX RECOMMENDATIONS

1. (MEDIUM — post-merge) Add hermetic tests for the two #1506 wiring fixes:
   - A test that the first-ever baseline seed (prev=None → new=value) triggers `_persist_bankroll_circuit_state`
   - A test that an EMA baseline change after `_build_trade_signal` (site 2) triggers persist
   These behaviors are correct in code and covered indirectly by the integration test, but direct regression pins would catch any future ordering regression.

2. (OPERATOR ACTION — before enabling flag) Apply migrations 073 + 074 to Supabase production via MCP `apply_migration`.

---

## NEXT GATE

Return to WARP🔹CMD for merge decision and operator migration application.
