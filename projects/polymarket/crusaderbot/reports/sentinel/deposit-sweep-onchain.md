# WARP•SENTINEL Validation — On-Chain Deposit Sweep

Branch: WARP/ROOT/deposit-sweep-onchain
Date: 2026-05-28 16:45 Asia/Jakarta
Environment: dev (paper runtime; live guards OFF)
Validation Tier: MAJOR
Source: projects/polymarket/crusaderbot/reports/forge/deposit-sweep-onchain.md
Authority: WARP🔹CMD explicitly assigned SENTINEL + merge + deploy authority.

---

## TEST PLAN

Phases against the actual diff (code is truth). Scope: per-user EOA→master
USDC consolidation + master-funded gas top-up. Both live guards remain OFF —
validating that the path is SAFE in paper posture and READY to enable.

## FINDINGS

### Phase 0 — Pre-test (PASS)
- Forge report present, correct path, 6 sections + metadata. PASS.
- No `phase*/` folders; code in locked structure. PASS.
- No migration claimed/needed (uses existing deposits/wallets columns). PASS.

### Phase 1 — Functional (PASS)
- sweep_deposits branches on EXECUTION_PATH_VALIDATED && SWEEP_ONCHAIN_ENABLED (scheduler.py). Logical-only otherwise. PASS.
- sweep_usdc_to_master: balance read → dust skip → gas ceiling → gas top-up → signed transfer → status==1 (polygon_usdc.py). PASS.
- Deposits marked swept ONLY after a confirmed tx (scheduler _sweep_deposits_onchain). PASS.

### Phase 2 — Pipeline (PASS)
- Sweep is a post-deposit consolidation; does not touch RISK/EXECUTION trade path. PASS.

### Phase 3 — Failure modes (PASS)
- Both flags not set → PreflightError, no signing (polygon_usdc.py:201). PASS.
- Gas spike → PreflightError (polygon_usdc.py:223). PASS.
- Master can't fund top-up → PreflightError before any send (polygon_usdc.py:167). PASS.
- Per-user failure isolated: PreflightError/Exception logged + `continue`; deposit stays swept=FALSE (retried next run, no double-credit). Verified by test_onchain_sweep_continues_on_user_failure. PASS.
- Dust skip does not mark swept (test_onchain_sweep_skips_dust_without_marking). PASS.
- USDC transfer revert → RuntimeError, deposit not marked swept. PASS.

### Phase 4 — Async safety (PASS)
- Cron max_instances=1 → sequential; master gas-top-up nonces cannot race. PASS.
- asyncio + asyncpg only; no threading. PASS.

### Phase 5 — Risk rules (PASS)
- SWEEP_ONCHAIN_ENABLED + EXECUTION_PATH_VALIDATED both default False (config.py:147,149 / 149 guard). UNCHANGED activation guards. PASS.
- Kelly untouched. No silent failures (every skip/fail logged). PASS.
- Private keys never logged (grep clean). PASS.

### Phase 6 — Latency (N/A)
- Batch nightly job; on-chain confirmation inherently slow. Not latency-bound. N/A.

### Phase 7 — Infra (PASS)
- Reuses cached AsyncWeb3 + master_wallet + vault.get_decrypted_pk (existing tested). No new external dep. PASS.

### Phase 8 — Telegram (N/A)
- No user-facing surface; audit breadcrumbs `deposit_sweep_onchain` written per user. PASS.

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

Test evidence: 6 sweep tests + full suite 1827 passed; ruff + py_compile clean.

## GO-LIVE STATUS

APPROVED — Score 94/100, 0 critical. SAFE in current paper posture (double-gated
OFF). Authorizes MERGE of the guarded-OFF code; does NOT flip or enable any
guard.

## FIX RECOMMENDATIONS

Operational, for the eventual enablement (not merge blockers):
1. Fund the master wallet with MATIC before enabling — top-ups and the master's own gas come from it.
2. Enable SWEEP_ONCHAIN_ENABLED for a small cohort first; watch audit `deposit_sweep_onchain` + on-chain confirmations before broad enablement.
3. Future: migrate custody to Gnosis-Safe proxies + Polymarket Builder relayer for gasless sweeps (removes per-wallet MATIC top-ups).

## TELEGRAM PREVIEW

No user-facing change. Operator observes consolidation via audit log
(`deposit_sweep_onchain`: user_id, tx_hash, amount_usdc, gas_topup_matic).

---

State: PROJECT_STATE.md updated. NEXT GATE → WARP🔹CMD final decision / merge.
