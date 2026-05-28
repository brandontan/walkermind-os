# WARP•SENTINEL Validation — SafeCustody + Cutover Dispatch

Branch: WARP/ROOT/safe-custody-cutover
Date: 2026-05-28 19:45 Asia/Jakarta
Environment: dev (paper runtime; all live guards OFF; CUSTODY_MODE default 'eoa')
Validation Tier: MAJOR
Source: projects/polymarket/crusaderbot/reports/forge/safe-custody-cutover.md
Authority: WARP🔹CMD explicitly assigned SENTINEL + merge + deploy authority for this lane.

---

## TEST PLAN

Phases against the actual diff (code is truth, not the forge claim). Scope:
the custody dispatcher + SafeCustody capital paths + the call-site swaps in
`wallet/withdrawals.py` and `scheduler._sweep_deposits_onchain`. Triple-gated
behind EXECUTION_PATH_VALIDATED + CUSTODY_MODE='safe' + relayer-configured.

## FINDINGS

### Phase 0 — Pre-test (PASS)
- Forge report at correct path, 6 sections + metadata. PASS.
- PROJECT_STATE + CHANGELOG updated (below). PASS.
- No `phase*/` folders; code in locked structure. PASS.
- Implementation evidence: `wallet/custody.py` + tests + call-site swaps. PASS.

### Phase 1 — Functional (PASS)
- Dispatcher routes EOA by default (`CUSTODY_MODE` default = 'eoa', config.py:151). PASS.
- Dispatcher routes Safe + configured → SafeCustody. PASS.
- Dispatcher routes Safe + unconfigured → BuilderRelayerUnavailable (no fallback). PASS (`wallet/custody.py:_ensure_safe_mode_wired`).
- SafeCustody.transfer_usdc happy path returns dict with `tx_hash`. PASS.
- SafeCustody.sweep dust-skip never invokes execute. PASS.

### Phase 2 — Pipeline placement (PASS)
- Dispatcher sits at the post-approval settlement boundary, not before the risk gate. RISK→EXECUTION ordering preserved. PASS.

### Phase 3 — Failure modes (PASS)
- EXECUTION_PATH_VALIDATED=false → PreflightError (`wallet/custody.py:122`). PASS.
- Non-positive amount → PreflightError. PASS.
- Relayer unconfigured (mode='safe') → BuilderRelayerUnavailable. PASS.
- Master-Safe balance insufficient → PreflightError before any execute. PASS (`wallet/custody.py:145`).
- Empty signer in sweep → PreflightError. PASS.
- `response.wait()` returns None → RuntimeError. PASS.

### Phase 4 — Async safety (PASS)
- Sync SDK (`client.execute`, `response.wait`) wrapped in `asyncio.to_thread` — event loop never blocked. PASS.
- No threading; asyncio + asyncpg only. PASS.
- Cron sweep is `max_instances=1`; sequential per-user processing → no relayer nonce race. PASS.

### Phase 5 — Risk rules (PASS)
- Activation guards untouched: ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED all default False (config.py:148–150). PASS.
- Kelly (a=0.25) untouched. PASS.
- No silent failures: every refusal logged + typed; no `except: pass`. PASS.
- Private keys never logged (grep clean across the diff). PASS.

### Phase 6 — Latency (N/A)
- Capital-exit and sweep are batch / async settlement; on-chain confirmation is inherently multi-second. Not a low-latency path. N/A.

### Phase 7 — Infra (PASS)
- Reuses cached AsyncWeb3, master_wallet, relayer SDK foundation (#1405). No new external dep beyond what already shipped. PASS.

### Phase 8 — Telegram (PASS)
- Audit breadcrumbs `safe_transfer_usdc_confirmed` + `safe_sweep_confirmed` emitted on success; operator can observe via audit_log. PASS.

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

Test evidence: 13 SafeCustody/dispatcher tests + full suite 1860 passed; ruff + py_compile clean.

## GO-LIVE STATUS

APPROVED — Score 94/100, 0 critical. SAFE in the current paper / EOA posture:
default `CUSTODY_MODE='eoa'` keeps every call routed to the already-shipped
polygon_usdc paths. The Safe path is triple-gated and unreachable without an
explicit owner-side flip of CUSTODY_MODE + relayer enablement + credentials.
Authorizes MERGE of the guarded code; does NOT flip or enable any guard.

## FIX RECOMMENDATIONS

Operational, for the eventual Safe-mode enablement (not merge blockers):
1. Acquire Builder Program credentials (polymarket.com/settings?tab=builder); set as Fly secrets.
2. Flip `USE_BUILDER_RELAYER=true`. Verify `is_relayer_configured()` returns True.
3. Run a single test withdrawal via SafeCustody (small amount, manual approval) to validate the relayer round-trip end-to-end.
4. Flip `CUSTODY_MODE='safe'` for a small cohort; watch `safe_transfer_usdc_confirmed` + `safe_sweep_confirmed` audits and on-chain Safes before broadening.

## TELEGRAM PREVIEW

No new user-facing surface. Operator observes via audit log:
- `safe_transfer_usdc_confirmed`: master_safe, destination, amount, tx_hash.
- `safe_sweep_confirmed`: from_safe, master_safe, amount, tx_hash.

---

State: PROJECT_STATE.md updated. NEXT GATE → WARP🔹CMD merge + operator-side enablement.
