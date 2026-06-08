# WARP•FORGE Report — staging-proof-clob-v2

Branch: `WARP/staging-proof-clob-v2`
Role: WARP•FORGE
Validation Tier: **STANDARD** (test-harness + CI tooling; ZERO production runtime change)
Claim Level: **NARROW INTEGRATION** (wires an existing harness onto an already-merged backend; the broker proof itself is operator-driven and out of this environment)
Validation Target: making the already-merged `ClobV2Client` (py-clob-client-v2, `USE_CLOB_V2`) provable against a REAL Polymarket broker through the existing WARP-74 live-reconcile staging harness, selectable end-to-end without code edits.
Not in Scope: running the broker proof itself (needs a Polymarket-permitted egress + throwaway funded wallet — operator-driven); flipping `USE_CLOB_V2=1` in prod; the post-proof retirement lane (deleting the v1/pysdk backends + dropping old libs); GTD support in `ClobV2Client`.

---

## 1. What was built

The WARP-97 cutover (`ClobV2Client`, PR #1720) merged **default-OFF** and was only
proven against a fake injected SDK (`tests/test_clob_v2.py`). The remaining gate
before `USE_CLOB_V2=1` can be flipped in prod is the WARP-74 live-broker staging
proof — but that harness defaulted to the polymarket-client backend and had no way
to select the new v2 backend.

This lane closes that gap with three surgical, runtime-inert changes so the SAME
five reconcile acceptance cases can be driven through the **py-clob-client-v2**
backend against a real broker:

1. **Harness backend selection.** `tests/staging/test_live_reconcile_staging.py::_staging_settings`
   now honours a `USE_CLOB_V2` env toggle, giving a 3-way backend select that
   matches the production factory precedence (`v2 > pysdk > legacy`). Because the
   harness already builds its client via the production factory
   `get_clob_client()`, setting `USE_CLOB_V2=1` is sufficient — the v2 client is
   constructed exactly as prod would and receives the **same** `_derived` L2
   credentials the harness already provisions in `_ensure_staging_creds` (the
   factory's v2 branch resolves creds via `effective_credentials()`, the identical
   cache). No new auth path.

2. **Operator dispatch input.** `.github/workflows/staging-proof-fly.yml` gains a
   `use_clob_v2` boolean dispatch input (takes precedence over `use_pysdk_clob`,
   mirroring the factory), threaded into the one-off Fly machine as `USE_CLOB_V2`
   env, plus a **CLOB backend** row in the mobile job summary so the §4 evidence
   bundle records which backend produced the result.

3. **Runbook.** `docs/runbooks/warp74-staging-proof.md` adds the `USE_CLOB_V2` /
   `USE_PYSDK_CLOB` env rows and a new **§7 — CLOB v2 cutover validation** that
   documents the run (Fly dispatch + local invocation), exactly what it proves
   about the v2 backend (build → EIP-712 sign → POST → broker-accept → readback on
   the native v2 order struct, builder attribution), and the acceptance bar.

## 2. Current system architecture

```
operator dispatch (Actions: use_clob_v2=true)
        │  USE_CLOB_V2=1 (machine env)
        ▼
tests/staging/test_live_reconcile_staging.py
   _staging_settings()  ──reads USE_CLOB_V2 env──▶ Settings(USE_CLOB_V2=True, USE_REAL_CLOB=True, staging wallet)
        │
   _ensure_staging_creds()  ──derives/creates L2 creds once──▶ clob._derived cache
        │
   get_clob_client(settings)   [PRODUCTION FACTORY — unchanged]
        │  USE_CLOB_V2 branch (precedence > USE_PYSDK_CLOB)
        │  creds via effective_credentials() = env | _derived
        ▼
   ClobV2Client (py-clob-client-v2)  ──post_order / cancel / get_open_orders / get_fills──▶ REAL Polymarket CLOB
        ▲
   reconcile / kill-switch / drift modules drive it via clob_factory (5 cases)
```

The selection is the only moving part; everything downstream (factory, v2 client,
reconcile logic, evidence/sentinel determination) is reused as-is.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — `_staging_settings()` reads `USE_CLOB_V2` env (3-way backend select; sets `USE_CLOB_V2` on the copied Settings).
- `.github/workflows/staging-proof-fly.yml` — `use_clob_v2` dispatch input; `USE_CLOB_V2` machine env + forwarded in the env loop; CLOB-backend row in the job summary.
- `projects/polymarket/crusaderbot/docs/runbooks/warp74-staging-proof.md` — `USE_CLOB_V2` / `USE_PYSDK_CLOB` env-table rows; new §7 v2 cutover validation procedure + acceptance.

Created:
- `projects/polymarket/crusaderbot/reports/forge/staging-proof-clob-v2.md` — this report.

State sync:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Status lead + `[COMPLETED]` bullet + WARP-97 `[NEXT PRIORITY]` bullet updated (proof gate now runnable).
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane-closure entry prepended.

## 4. What is working

- `python -m pytest projects/polymarket/crusaderbot/tests/test_clob_v2.py -q` → **12 passed** (factory selection / fail-fast / `__slots__` / builder-secret alias unchanged).
- `python -m py_compile …/tests/staging/test_live_reconcile_staging.py` → compiles clean.
- `.github/workflows/staging-proof-fly.yml` parses as valid YAML (`yaml.safe_load`).
- Credential-flow trace confirmed: the factory v2 branch reads `effective_credentials(s)` = env | `_derived`, the exact cache the harness populates — so a fresh throwaway wallet's auto-derived creds reach the v2 client without a new path.

## 5. Known issues

- The broker proof itself has **not** been run here: it requires a Polymarket-permitted egress (Fly `nrt` etc.) + a throwaway wallet with minimal USDC, which is outside this environment. Status remains "gate runnable, not yet green for v2".
- `ClobV2Client` raises on `GTD` (needs an expiration arg) — the staging cases use GTC only, so this does not block the proof; tracked as a follow-up.
- The Fly workflow's machine still installs deps from `pyproject.toml`, which (until the retirement lane) includes both old CLOB libs alongside py-clob-client-v2 — harmless for the proof, just slightly larger install.

## 6. What is next

- **Operator:** dispatch the Fly proof with `use_clob_v2` checked (region `nrt`, `signature_type 1`, `allow_fills=false`); run case3 + case2 + case4. Confirm the job-summary CLOB-backend row = `py-clob-client-v2 (USE_CLOB_V2)` and capture the §4 evidence bundle.
- **On green:** WARP🔹CMD sets `USE_CLOB_V2=1` on the prod app (real-path cutover; live still gated by `ENABLE_LIVE_TRADING`).
- **Then:** retirement lane — delete `sdk_client.py` + the v1 `adapter.py` order-building + the orphaned `polymarket.py` legacy path; drop `polymarket-client` + `py-clob-client` from `pyproject.toml`.
- **Follow-up:** GTD support in `ClobV2Client`.

Suggested Next Step: operator runs the v2 staging proof (Fly, `use_clob_v2=true`, case3 first); report the per-case PASS + CLOB-backend = py-clob-client-v2 back to WARP🔹CMD for the `USE_CLOB_V2=1` go/no-go.

---

Validation Handoff (per tier):

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/staging-proof-clob-v2.md
Tier: STANDARD
```
