# FORGE REPORT — Phase 10.10 Deployment Hardening Contract Closure

## Metadata
- Timestamp (Asia/Jakarta): 2026-04-24 09:31
- Branch: NWAP/deployment-hardening-traceability-repair
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation target: deployment/startup/health/readiness/restart/rollback/smoke-test contract only

## Scope
- `projects/polymarket/polyquantbot/Dockerfile`
- `projects/polymarket/polyquantbot/fly.toml`
- `projects/polymarket/polyquantbot/docs/operator_runbook.md`
- `projects/polymarket/polyquantbot/docs/fly_runtime_troubleshooting.md`
- State/report sync files under `projects/polymarket/polyquantbot/state/` and `projects/polymarket/polyquantbot/reports/forge/`

## Exact changes
1. Dockerfile hardened as authoritative runtime contract:
   - Explicit runtime env defaults (`PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `PORT`).
   - Docker `HEALTHCHECK` normalized to a single-line bounded `/health` aliveness probe so the container contract is parse-safe and Fly-aligned.
2. `fly.toml` synchronized with deployment contract:
   - Added `[deploy] strategy = "immediate"` to avoid overlapping Telegram pollers in single-machine mode.
   - Kept pinned single-machine runtime and `/health` + `/ready` check split.
3. Operator docs synchronized:
   - Restart policy truth, image-based rollback path, config/secret drift caveat, and post-deploy smoke-test contract are now explicit and bounded.
4. State truth synchronized:
   - Deployment Hardening implementation checklist items remain closed in `WORKTODO.md` while Priority 2 done-condition gate remains pending MAJOR validation.
   - Active-lane wording remains closure-ready pending SENTINEL MAJOR validation path.

## Validation run (FORGE-X local)
- `python3 -m py_compile projects/polymarket/polyquantbot/scripts/run_api.py`
- `python3 -m py_compile projects/polymarket/polyquantbot/server/main.py`
- Manual repo-truth review confirmed exact branch traceability now matches the authoritative PR branch.

## Outcome
- Deployment Hardening contract closure is complete at repo-truth level for the scoped deploy/startup/health/readiness/restart/rollback/smoke-test boundary.
- SENTINEL MAJOR validation remains required before merge decision.
