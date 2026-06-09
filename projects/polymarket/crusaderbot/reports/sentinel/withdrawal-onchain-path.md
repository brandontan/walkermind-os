# WARP•SENTINEL Validation — C1: On-Chain Withdrawal Capital Path

Branch: WARP/ROOT/withdrawal-onchain-path
Date: 2026-05-28 15:30 Asia/Jakarta
Environment: dev (paper runtime; live guards OFF)
Validation Tier: MAJOR
Source: projects/polymarket/crusaderbot/reports/forge/withdrawal-onchain-path.md
Authority: WARP🔹CMD explicitly assigned SENTINEL + merge + deploy authority.

---

## TEST PLAN

Phases run against the actual diff (code is truth, not the FORGE report):
0 pre-test · 1 functional · 2 pipeline placement · 3 failure modes ·
4 async safety · 5 risk rules · 6 latency · 7 infra · 8 telegram.
Scope: the withdrawal capital-exit path only. Live guards remain OFF — this
validates that the path is SAFE in the current paper posture and READY to flip.

## FINDINGS

### Phase 0 — Pre-test (PASS)
- Report present, correct path, 6 sections + metadata — PASS.
- PROJECT_STATE.md updated (Status, COMPLETED, IN PROGRESS, NEXT PRIORITY) — PASS.
- No `phase*/` folders; new code in locked domain structure — PASS.
- Implementation evidence: integrations/polygon_usdc.py + wallet/withdrawals.py — PASS.

### Phase 1 — Functional (PASS)
- Manual mode: approve_withdrawal (wallet/withdrawals.py:199) → _settle_withdrawal → transfer. PASS.
- Auto mode: create_withdrawal_request (wallet/withdrawals.py:62-92) fires _settle_withdrawal inline. Verified the prior gap (auto rows debited but never sent) is closed. PASS.
- Settlement states: processing → completed+tx_hash (withdrawals.py:172-180) | failed (+refund on preflight) | failed (no refund post-broadcast). PASS.

### Phase 2 — Pipeline placement (PASS)
- RISK→EXECUTION preserved: ledger debit is atomic at request time; on-chain transfer is post-approval settlement, never bypasses a guard. PASS.

### Phase 3 — Failure modes (PASS)
- Guard OFF → PreflightError before any signing (polygon_usdc.py:73). PASS.
- Gas ceiling exceeded → PreflightError (polygon_usdc.py:91). PASS.
- Insufficient hot-pool USDC / MATIC → PreflightError (polygon_usdc.py:99,105). PASS.
- Pre-broadcast failure → ledger refunded (withdrawals.py _settle_withdrawal PreflightError branch). PASS.
- Post-broadcast revert/timeout → 'failed', NO refund, operator reconciles. Conservative (never creates money). PASS.
- Revert assertion: status != 1 → RuntimeError (polygon_usdc.py:126). PASS.

### Phase 4 — Async safety (PASS)
- No threading; asyncio + asyncpg only. PASS.
- Concurrent double-approval: UPDATE ... WHERE status='pending' RETURNING is atomic — second caller gets None → ValueError before any transfer. No double-send. PASS.
- Idempotency: existing tx_hash short-circuits (_attempt_onchain_transfer); partial-unique index idx_withdrawals_tx_hash is the DB backstop. PASS.

### Phase 5 — Risk rules (PASS)
- ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED all default False (config.py:148-150) — UNCHANGED. PASS.
- Kelly (a=0.25) untouched. PASS.
- No silent failures; every exception logged + state-recorded. PASS.

### Phase 6 — Latency (N/A)
- On-chain settlement is inherently slow (180s receipt timeout) and not a low-latency path; no SLA regression. N/A.

### Phase 7 — Infra (PASS)
- Reuses cached AsyncWeb3 (_get_w3) + master_wallet signing; migration 060 additive + idempotent (ADD COLUMN IF NOT EXISTS). PASS.

### Phase 8 — Telegram (PASS)
- Admin approve handler wired (bot/handlers/admin.py:603) with audit breadcrumb. PASS.

## CRITICAL ISSUES

None found.

## STABILITY SCORE

| Dimension | Weight | Score |
|---|---|---|
| Architecture | 20 | 19 |
| Functional | 20 | 19 |
| Failure modes | 20 | 18 |
| Risk rules | 20 | 20 |
| Infra + Telegram | 10 | 9 |
| Latency | 10 | 9 |
| TOTAL | 100 | 94 |

Test evidence: 26 hermetic withdrawal tests + full suite 1823 passed; ruff + py_compile clean.

## GO-LIVE STATUS

APPROVED — Score 94/100, 0 critical. The withdrawal capital-exit path is
SAFE in the current paper posture (guards OFF = deferred no-op) and correctly
wired for both manual and auto approval modes once a guard flip occurs. This
verdict authorizes MERGE of the guarded-OFF code; it does NOT itself flip any
activation guard.

## FIX RECOMMENDATIONS

Operational prerequisites for the eventual go-live flip (not merge blockers):
1. Fund the master hot-pool with USDC + MATIC before flipping EXECUTION_PATH_VALIDATED — on-chain deposit sweep is still logical-only, so the pool is not auto-funded.
2. Optional: split a dedicated WITHDRAWAL_GAS_GWEI_MAX knob (currently reuses INSTANT_REDEEM_GAS_GWEI_MAX=200).
3. Staged rollout: keep approval_mode='manual' for the first live cohort so each transfer is operator-gated; enable 'auto' only after observed clean settlement.

## TELEGRAM PREVIEW

Admin approve flow (existing): operator taps approve on a pending withdrawal →
audit `approve_withdrawal` written → settlement fires (deferred in paper). On a
live failure the row shows 'failed' with onchain_error; preflight failures
auto-refund the user's balance.

---

State: PROJECT_STATE.md updated (NEXT GATE → WARP🔹CMD final decision / merge).
