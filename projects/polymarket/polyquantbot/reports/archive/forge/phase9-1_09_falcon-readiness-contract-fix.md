# Phase 9.1 — Falcon Readiness Contract Fix (Runtime-Surface)

**Date:** 2026-04-21 02:56
**Branch:** feature/fix-phase-9-1-falcon-readiness-contract
**Task:** Fix Falcon readiness/runtime contract mismatch so missing `FALCON_API_KEY` under `FALCON_ENABLED=true` is represented as readiness-invalid state instead of failing app creation.

## 1. What was built

- Updated Falcon env parsing contract so `FALCON_ENABLED=true` without `FALCON_API_KEY` no longer raises during app construction.
- Preserved readiness-surface invalid semantics through existing `/ready` and `/beta/admin` payload fields (`enabled_without_api_key=true`, `config_valid_for_enabled_mode=false`) by allowing app boot to complete and readiness evaluation to run.
- Kept strict validation for `FALCON_TIMEOUT <= 0` and missing enabled-mode base URL unchanged.

## 2. Current system architecture (relevant slice)

1. `projects/polymarket/polyquantbot/server/main.py` constructs `FalconSettings` during app creation.
2. `projects/polymarket/polyquantbot/server/api/routes.py:/ready` computes Falcon readiness booleans from `FalconSettings`.
3. With this fix, missing key in enabled mode is surfaced by readiness payload booleans (invalid config) instead of aborting app creation with runtime exception.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/polyquantbot/configs/falcon.py`
- `projects/polymarket/polyquantbot/reports/forge/phase9-1_09_falcon-readiness-contract-fix.md`
- `PROJECT_STATE.md`

## 4. What is working

- Falcon readiness contract for the targeted runtime path now matches the runtime-surface expectation: app creation remains evaluable when Falcon is enabled without API key.
- Local py_compile check passes for touched Python config module.
- Canonical runtime-proof command still executes and now proceeds to dependency install stage before blocking on package-index reachability in this runner.

## 5. Known issues

- Full runtime-proof closure remains blocked in this environment by dependency installation failures (proxy 403 / direct network unreachable), so closure-pass artifacts were not produced.
- GitHub Actions rerun could not be triggered from this environment because GitHub CLI/auth tooling is unavailable here.

## 6. What is next

- COMMANDER review this MAJOR/NARROW readiness-contract fix.
- Trigger `.github/workflows/phase9_1_runtime_proof.yml` on GitHub and verify end-to-end pass in the external capable runner.
- If and only if full workflow passes, refresh `projects/polymarket/polyquantbot/reports/forge/phase9-1_01_runtime-proof-evidence.log`, write `projects/polymarket/polyquantbot/reports/forge/phase9-1_09_runtime-proof-closure-pass.md`, then sync `PROJECT_STATE.md` and `ROADMAP.md` to close 9.1 and move to 9.2.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Falcon readiness/runtime contract only for `/ready` evaluability when `FALCON_ENABLED=true` and API key missing
Not in Scope      : live trading, strategy logic, wallet lifecycle expansion, dashboard expansion, broad Falcon feature work, Phase 9.2/9.3
Suggested Next    : SENTINEL on PR head branch after external workflow proof is green
