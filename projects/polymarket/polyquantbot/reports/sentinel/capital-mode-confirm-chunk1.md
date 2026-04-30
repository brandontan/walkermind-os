# WARP•SENTINEL Report — capital-mode-confirm chunk 1

**Branch:** WARP/capital-mode-confirm
**PR:** #815
**Validated by:** WARP•SENTINEL
**Timestamp:** 2026-04-30 13:30 Asia/Jakarta
**Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** capital-mode-confirm chunk 1 — DB layer, guard method, API endpoints, Telegram wiring
**Not in Scope:** check_with_receipt() wired to live execution paths (confirmed not wired per Claim Level)

---

## Environment

- Runner: Cursor Cloud Agent
- Branch validated: WARP/capital-mode-confirm (PR #815)
- Files validated: 7 runtime Python files + 1 SQL migration
- Forge report: Not present in branch (chunk 5 of 5 per commit message — task declared SENTINEL before forge report chunk). WARP🔹CMD issued SENTINEL TASK directly with explicit scope — proceeding under WARP🔹CMD authority.
- py_compile: PASS (7/7 files)
- No phase*/ folders introduced: PASS
- No threading: PASS (asyncio only throughout)
- ENABLE_LIVE_TRADING guard: PASS — live_execution_control.py:160 enforces via os.getenv()

---

## Validation Context

Claim: NARROW INTEGRATION — DB schema + store + API endpoints + guard method + Telegram wiring are integrated. check_with_receipt() exists but is NOT wired to any active execution path. paper_beta_worker.py and clob_execution_adapter.py still call check() only.

---

## Phase 0 Checks

- [x] Forge report path: Not present (WARP🔹CMD explicit SENTINEL TASK override accepted)
- [x] PROJECT_STATE.md updated with full timestamp: 2026-04-30 11:11 (pre-existing; will be updated by this report)
- [x] py_compile — 7/7 Python files: PASS
- [x] No phase*/ folders in PR: PASS
- [x] No hardcoded secrets: PASS (secrets.token_hex() stdlib only)
- [x] No threading (asyncio only): PASS
- [x] Kelly α = 0.25: PASS (capital_mode_config.py:46 `KELLY_FRACTION: float = 0.25`)
- [x] Max position <= 10%: PASS (MAX_POSITION_FRACTION_CAP: float = 0.10, capital_mode_config.py:47)
- [x] Daily loss limit = -$2000: PASS (_DEFAULT_DAILY_LOSS_LIMIT_USD: float = -2000.0, capital_mode_config.py:55)
- [x] Drawdown limit 8%: PASS (DRAWDOWN_LIMIT_CAP: float = 0.08, capital_mode_config.py:48)
- [x] ENABLE_LIVE_TRADING guard not bypassed: PASS (live_execution_control.py:160)

Phase 0: ALL PASS

---

## Findings

### 1. check_with_receipt() guard chain — live_execution_control.py

**a. self.check() called FIRST — PASS**
live_execution_control.py:242: `self.check(state, provider=provider, wallet_id=wallet_id)` is the first call in check_with_receipt(). The 5-gate synchronous chain (kill_switch → mode → ENABLE_LIVE_TRADING → config.validate() → provider zero-field) runs before any async DB work.

**b. store.get_active() called after self.check() — PASS**
live_execution_control.py:248: `active = await store.get_active(self._config.trading_mode)` is invoked after self.check() completes without raising.

**c. active is None → _block() → raises — PASS**
live_execution_control.py:256-262: `if active is None: self._block(...)`. _block() at line 273-279 raises `LiveExecutionBlockedError` unconditionally. The `log.info("live_execution_guard_with_receipt_passed", ...)` at line 264 is NOT reachable when active is None.

**d. Dead code after _block() in exception handler — NEEDS-FIX (non-critical)**
live_execution_control.py:250-254: In the exception handler for store.get_active(), `self._block(...)` is followed by `return` (line 254). Since _block() always raises LiveExecutionBlockedError, the `return` is dead code. Current behavior is CORRECT — guard does raise. Risk: if _block() is ever refactored to be non-raising (e.g., returns a bool), the guard would silently pass without the `return` being a safety net. This is a latent refactor hazard, not a current safety failure.
- Verdict for this item: NEEDS-FIX (low priority) — remove dead `return` or add comment explaining it is intentional defensive code.

### 2. Two-step token flow — public_beta_routes.py

**a. Step 1 token issuance — PASS**
public_beta_routes.py:409: `token = secrets.token_hex(8)` (16 hex chars / 64 bits entropy). Stored under operator_id with TTL at line 410-415.

**b. secrets.compare_digest() — PASS**
public_beta_routes.py:449-451: `secrets.compare_digest(str(pending["token"]), body.acknowledgment_token)` — timing-safe comparison confirmed.

**c. pop() BEFORE insert() — PASS (token consumed even if DB write fails)**
public_beta_routes.py:465: `_PENDING_CAPITAL_CONFIRMS.pop(body.operator_id, None)` executes unconditionally before `store.insert()` at line 467. If store.insert() fails (returns None), the token is already consumed. No replay possible on DB failure — endpoint returns HTTP 500, operator must request a new token. Correct behavior for an anti-misclick guard.

**d. Expiry cleanup runs at start of EVERY call — PASS**
public_beta_routes.py:401-405: The expiry loop runs at the shared entry point (line 401) before the step 1 / step 2 branch. Both step 1 (no token) and step 2 (with token) paths pass through this cleanup unconditionally. PASS.

**e. mode hardcoding consistency — CONDITIONAL**
- Pending dict: `"mode": "LIVE"` (line 412)
- store.insert(): `mode="LIVE"` (line 469)
- store.revoke_latest(): `mode="LIVE"` (line 528)
- cfg.trading_mode is asserted == "LIVE" at line 356 before any token action

The route hard-codes "LIVE" rather than using `cfg.trading_mode`. This is consistent in all three locations and the route already rejects non-LIVE (line 356). However, if PAPER confirmation is ever needed, all three sites must be updated manually — no single constant to change.
- Verdict: CONDITIONAL — works correctly for current LIVE-only scope. Fragility risk for future PAPER extension. Document or extract constant.

### 3. Operator auth

**PASS**
- `/capital_mode_confirm` at line 340: `__: None = Depends(_require_operator_api_key)`
- `/capital_mode_revoke` at line 507: `__: None = Depends(_require_operator_api_key)`
- Both endpoints use FastAPI Depends injection — no unauthenticated path exists. _require_operator_api_key() at line 158 raises HTTP 403 on missing/invalid key.

### 4. Revoke single-step (no token) — APPROVED with risk flag

**PASS — operator auth confirmed**
public_beta_routes.py:503-507: revoke is single-step, no token required, but requires X-Operator-Api-Key header.

**Risk flag for WARP🔹CMD:**
Revocation is intentionally easier than confirmation (no token, single step). This is correct for incident response speed — a compromised or misclick scenario requires immediate revoke capability. The asymmetry is a documented design choice, not a defect. WARP🔹CMD should acknowledge this design decision explicitly in the merge review.

### 5. DB schema — 002_capital_mode_confirmations.sql

**Partial index — PASS**
SQL migration line 31-34: `CREATE INDEX IF NOT EXISTS idx_capital_mode_confirmations_active ON capital_mode_confirmations (mode, confirmed_at DESC) WHERE revoked_at IS NULL`. The get_active() query at store line 179: `WHERE mode = $1 AND revoked_at IS NULL ORDER BY confirmed_at DESC LIMIT 1` — matches the partial index exactly. Hot path will use the narrow index.

**_apply_schema() idempotency — PASS**
database.py:527: `await conn.execute(_DDL_CAPITAL_MODE_CONFIRMATIONS)` is called inside _apply_schema(). DDL uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` — idempotent. Applied at end of priority sequence (after settlement tables), correct ordering per AGENTS.md pipeline.

**ON CONFLICT DO NOTHING — PASS**
store.py:88: `ON CONFLICT (confirmation_id) DO NOTHING`. UUID (uuid4().hex) collision probability is negligible (2^-122). Correct.

### 6. Store fail-safe — main.py

**PASS**
main.py:443-447: `if state.db_client is not None: _app.state.capital_mode_confirmation_store = CapitalModeConfirmationStore(db=state.db_client)`

If db_client is None, capital_mode_confirmation_store is never set on app.state. Both endpoints use `getattr(request.app.state, "capital_mode_confirmation_store", None)` and raise HTTP 503 when store is None (public_beta_routes.py:390-399 and 514-524). No None dereference possible — PASS.

### 7. CLAIM LEVEL check — CRITICAL

**PASS — CLAIM LEVEL: NARROW INTEGRATION confirmed**

- paper_beta_worker.py:87: `self._live_guard.check(STATE, provider=resolved_provider)` — calls check(), NOT check_with_receipt()
- clob_execution_adapter.py:282: `self._guard.check(state, provider=provider, wallet_id=wallet_id)` — calls check(), NOT check_with_receipt()

check_with_receipt() is DEFINED but not wired to any active execution path. No BLOCKER. Tier upgrade NOT required for this chunk.

---

## Score Breakdown

| Criterion | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 19/20 | Solid layered design; dead `return` latent hazard noted |
| Functional | 20% | 19/20 | All 7 validation items pass; mode hardcoding fragility |
| Failure modes | 20% | 20/20 | Token consume-before-insert, 503 on no store, _block() always raises |
| Risk constants | 20% | 20/20 | Kelly=0.25, max_position=10%, loss=-2000, drawdown=8% all locked |
| Infra + Telegram | 10% | 9/10 | Store wired idempotently; Telegram in _INTERNAL_COMMANDS |
| Latency / async | 10% | 10/10 | asyncio throughout, no threading, no blocking calls |

**Total: 97/100**

---

## Critical Issues

None found.

---

## Status

**GO-LIVE: APPROVED**
Score: 97/100. Critical issues: 0.

All 7 validation items from WARP🔹CMD SENTINEL TASK confirmed. Two non-critical findings (dead `return` in exception handler, mode hardcoding fragility) deferred to KNOWN ISSUES.

---

## PR Gate Result

**APPROVED for merge** — subject to WARP🔹CMD final decision.
Branch: WARP/capital-mode-confirm
PR target: main (merge-order truth: source WARP•FORGE PR #815 is open, PR targets main)

---

## Broader Audit Finding

- The expiry cleanup loop for _PENDING_CAPITAL_CONFIRMS is in-process (module-level dict). Gunicorn/uvicorn multi-worker deployments would shard the dict across workers, meaning a token issued by worker A cannot be consumed by worker B. Acceptable for current single-worker deployment. Must be noted before scaling to multi-worker.

---

## Reasoning

Seven validation items per WARP🔹CMD task brief, all verified against source code (file:line evidence):
1. Guard chain order confirmed with explicit line references
2. Two-step token flow verified (timing-safe, consume-before-insert, expiry-on-every-call)
3. Both endpoints gated by _require_operator_api_key
4. Revoke single-step by design — operator auth still required
5. DB schema partial index matches query pattern exactly
6. Store fail-safe (503 on missing store) confirmed in both endpoints
7. Claim Level NARROW INTEGRATION confirmed — no execution path uses check_with_receipt()

---

## Fix Recommendations

**Priority 1 (non-critical, next WARP•FORGE pass):**
- live_execution_control.py:254 — Remove dead `return` after `self._block()` in exception handler, or add explicit comment: `# _block() always raises; return is defensive for future refactor safety`. This prevents silent guard bypass if _block() is ever refactored to non-raising.

**Priority 2 (low, next WARP•FORGE pass):**
- public_beta_routes.py:412,469,528 — Extract `"LIVE"` hardcode to a module-level constant (e.g., `_CONFIRM_MODE = "LIVE"`) to eliminate 3-site manual update risk if PAPER confirmation is ever added.

**Priority 3 (advisory, pre-scaling):**
- _PENDING_CAPITAL_CONFIRMS is a module-level dict — document single-worker requirement or migrate to Redis-backed pending store before multi-worker deployment.

---

## Out-of-scope Advisory

- check_with_receipt() wiring to execution paths (paper_beta_worker, clob_execution_adapter) is out of scope for this chunk. When wired, that transition must trigger a new MAJOR SENTINEL sweep before merge.
- Multi-worker pending token store is a scaling concern, not a correctness issue at current deployment.

---

## Deferred Minor Backlog

- [DEFERRED] Dead `return` after `self._block()` in check_with_receipt exception handler (live_execution_control.py:254) — found in WARP/capital-mode-confirm chunk 1
- [DEFERRED] mode="LIVE" hardcoded in 3 locations in public_beta_routes.py — extract to constant — found in WARP/capital-mode-confirm chunk 1

---

## Telegram Visual Preview

**Operator command surface (both in _INTERNAL_COMMANDS — operator chat-id gated):**

Step 1 (issue token):
```
/capital_mode_confirm
🟡 Capital mode confirm — step 1/2
• Token: `a3f9c21d4e7b8f05`
• Reply within 60s with: /capital_mode_confirm a3f9c21d4e7b8f05
• Gate snapshot:
  • enable_live_trading: ✅
  • capital_mode_confirmed: ✅
  • risk_controls_validated: ✅
  • execution_path_validated: ✅
  • security_hardening_validated: ✅
```

Step 2 (commit):
```
/capital_mode_confirm a3f9c21d4e7b8f05
✅ Capital mode confirmed — receipt persisted
• confirmation_id: abc123hex...
• operator_id: op_12345
• mode: LIVE
• confirmed_at: 2026-04-30T06:30:00+00:00
```

Revoke:
```
/capital_mode_revoke emergency halt
🛑 Capital mode confirmation revoked
• confirmation_id: abc123hex...
• revoked_by: op_12345
• revoked_at: 2026-04-30T06:35:00+00:00
• reason: emergency halt
```

Guard blocked (when check_with_receipt() is eventually wired):
```
live_execution_guard_blocked reason=capital_mode_no_active_receipt
→ operator must issue /capital_mode_confirm before live execution
```

---

Done — GO-LIVE: APPROVED. Score: 97/100. Critical: 0.
Branch: WARP/capital-mode-confirm
PR: #815
Report: projects/polymarket/polyquantbot/reports/sentinel/capital-mode-confirm-chunk1.md
State: PROJECT_STATE.md updated
NEXT GATE: Return to WARP🔹CMD for final merge decision.
