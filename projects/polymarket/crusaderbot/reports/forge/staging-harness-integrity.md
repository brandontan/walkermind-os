# WARP•FORGE — staging-harness-integrity

Validation Tier: MAJOR (proof-harness integrity + a CLOB error-mapping fix on the dormant pysdk backend)
Claim Level: NARROW INTEGRATION
Validation Target: (1) the staging-proof PASS/FAIL determination cannot be spoofed by a stale prior-run sentinel; (2) a pysdk `UserInputError` maps to `ClobConfigError`, not `ClobAuthError`; (3) the case2 mismatch sub-case posts a tick-aligned price.
Not in Scope: any change to `live_reconcile.py` / `complete_set_exec.py` / the case1 test (case1 is REPORT ONLY — see `case1-rollback-investigation.md`); LIVE flip (`allow_fills`/`ENABLE_LIVE_TRADING` stay gated).
Suggested Next Step: re-dispatch `all-broker` (nrt, `allow_fills=false`) on this branch's logic once merged — expect a TRUE green (8/8 incl. case2[mismatch]); then CMD decides on the case1 test-poll recommendation.

## 1. What was built

A batch fixing the META-BUG plus the two real all-broker failures (run 27026102440 = `2 failed, 6 passed, 1 skipped`, which the job badge wrongly reported green).

### (1) Harness false-green — META-BUG (the critical one)
The proof decides PASS/FAIL from an explicit `PROOF_RESULT=<PASS|FAIL>` sentinel the guest echoes, captured via `flyctl logs --app <app>`. That command streams EVERY machine in the app over a recent window, so a PRIOR run's `PROOF_RESULT=PASS` (a stopped machine Fly still buffers) leaked into this run's capture; the unscoped `grep PROOF_RESULT=PASS` then reported a FALSE PASS even though this run's pytest FAILED off the prior case3 PASS line.
Fix: a per-run nonce `PROOF_NONCE=<run_id>-<run_attempt>` is injected into the guest; the sentinel is now `PROOF_RESULT=<PASS|FAIL> <nonce>`; determination is delegated to `scripts/proof_result.sh <log> <nonce>` which fixed-string matches the nonce-tagged line. A stale line (different nonce) is impossible to pick up; a run that produced no sentinel is INCONCLUSIVE (job fails), never green.

### (2) case2 UserInputError mis-mapping (prod-relevant)
`_map_error` bucketed pysdk `UserInputError` (bad price/tick/decimals/size) into `ClobAuthError`. A client-side input/validation error is a CONFIG/usage problem, not auth — mis-bucketing would mis-route ops/retry to a credential cause. Now mapped to `ClobConfigError`. `SigningError` stays `ClobAuthError` (a signing failure is a key/credential problem).

### (3) case2[mismatch] test bug
The sub-case posted `price=max(_REST_PRICE*3, 0.30)`; with `_REST_PRICE=0.10`, `0.10*3 = 0.30000000000000004` (binary float) → broker rejects ">2 decimals". Now rounded to the tick (`round(..., 2)`), matching the other variants.

### (4) case1[rollback] — investigated, REPORT ONLY
Verdict: correct safety behavior + a test-timing gap (cancel is eventually-consistent; the test reconciles immediately with no poll, so `get_order` still reads LIVE → conservative `pending`). No prod change. See `reports/forge/case1-rollback-investigation.md`.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged). The proof harness (`.github/workflows/staging-proof-fly.yml`) gains a repo checkout + the shared `scripts/proof_result.sh` decision module (single source of truth, unit-tested). The pysdk CLOB backend (`PolymarketSdkClient`, dormant behind `USE_PYSDK_CLOB`) error taxonomy is corrected for `UserInputError`. No prod runtime path beyond the error-mapping line is touched.

## 3. Re-verification of prior PASSes (per CMD directive)

The stale-PASS leak can only mask a FAIL as a FALSE PASS — it can never make a genuinely-passing pytest run report passes. So a run whose captured pytest summary shows passes is genuinely green regardless of the (old) sentinel grep.

- **case3 run #13 (27025520356, machine 48e190eae11598):** captured pytest summary `1 passed, 8 deselected`; the `PROOF_RESULT=PASS` was emitted by that same machine after a real `1 passed`. → **REAL PASS** (the order placed, rested, readback fully mapped, kill-switch cancelled, post-kill poll empty).
- **case5 (test_case5_infra_degraded_falls_back_to_paper_and_alerts):** `PASSED` on the real machine 89954db66e0ed8 INSIDE the all-broker run 27026102440 (alongside that run's own FAIL sentinel). → **REAL PASS**, independently confirmed in-run; case5 places no real order (infra-degraded → paper fallback), so it is unaffected by broker timing.

Both are genuine; neither was a stale-leak artifact.

## 4. What is working

- `scripts/proof_result.sh`: PASS/FAIL/INCONCLUSIVE with correct exit codes; a stale prior-run PASS + current FAIL → FAIL; only-stale-PASS → INCONCLUSIVE. Verified by 4 harness tests + a direct shell run.
- `_map_error(UserInputError)` → `ClobConfigError` (not auth); unit test added.
- case2[mismatch] posts a tick-aligned price.
- `py_compile` clean on all edited Python; workflow YAML parses.

## 5. Known issues

- Full pytest (pydantic + polymarket-client) not runnable in this container; validated via `py_compile`, the shell harness, and the mapping logic. Authoritative confirmation = CI (mocked) + the next all-broker dispatch.
- case1 test-timing gap remains (by design — REPORT ONLY); CMD to decide on the recommended test-side poll.

## 6. What is next

- Re-dispatch `all-broker` (nrt, `allow_fills=false`) — expect a TRUE green now that the sentinel cannot be spoofed and case2[mismatch] is tick-aligned. case1 will still show `pending` until the test gains a poll (CMD decision).
- Then the only remaining gate is the owner-controlled LIVE flip.
