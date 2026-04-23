# FORGE-X Report — phase10-10_01_deployment-hardening-with-post-merge-state-sync

## 1) What was built
- Performed post-merge repo-truth sync for merged PR #752 by replacing stale `PROJECT_STATE.md` pre-merge wording with merged-main truth and explicit active Priority 2 Deployment Hardening lane tracking.
- Hardened deployment contract in `projects/polymarket/polyquantbot/Dockerfile` so container layout and runtime entrypoint are truthful (`python -m projects.polymarket.polyquantbot.scripts.run_api`) without nested copy-path ambiguity, with exception-safe healthcheck exit behavior.
- Hardened `projects/polymarket/polyquantbot/fly.toml` to match single-machine API+Telegram process model, explicit `/health` liveness check, and explicit `/ready` readiness check.
- Updated bounded deploy documentation (`projects/polymarket/polyquantbot/docs/operator_runbook.md` and `projects/polymarket/polyquantbot/docs/crusader_runtime_surface.md`) for restart-policy truth, rollback procedure truth, and reproducible post-deploy smoke tests, including portable log filtering examples.

## 2) Current system architecture (relevant slice)
- Runtime entrypoint: Docker and Fly deploy a single FastAPI process via `projects.polymarket.polyquantbot.scripts.run_api`, which boots `server.main` and starts embedded Telegram polling runtime in the same lifecycle.
- Health/readiness contract:
  - `/health` = liveness/process contract.
  - `/ready` = operational runtime-readiness visibility contract.
- Fly process model contract:
  - one running machine (`min_machines_running=1`, `max_machines_running=1`), `auto_stop_machines="off"`, `auto_start_machines=true`.
- Claim boundary remains FOUNDATION and paper-only; no live-trading or production-capital readiness claim introduced.

## 3) Files created / modified (full repo-root paths)
- Modified: `PROJECT_STATE.md`
- Modified: `projects/polymarket/polyquantbot/Dockerfile`
- Modified: `projects/polymarket/polyquantbot/fly.toml`
- Modified: `projects/polymarket/polyquantbot/docs/operator_runbook.md`
- Modified: `projects/polymarket/polyquantbot/docs/crusader_runtime_surface.md`
- Added: `projects/polymarket/polyquantbot/.dockerignore`
- Created: `projects/polymarket/polyquantbot/reports/forge/phase10-10_01_deployment-hardening-with-post-merge-state-sync.md`

## 4) What is working
- `PROJECT_STATE.md` now reflects merged-main truth for PR #752 and tracks Deployment Hardening as active Priority 2 lane.
- Docker runtime command is aligned with actual app package layout and no longer depends on nested copy target assumptions.
- Docker healthcheck no longer depends on unavailable curl binary in runtime stage; it now uses Python stdlib HTTP probe to `/health` with explicit exception-safe non-zero failure behavior.
- Fly runtime contract now explicitly checks both liveness (`/health`) and readiness (`/ready`) while keeping single-machine polling-safe posture.
- Operator runbook now includes bounded restart policy truth, rollback command path, and explicit post-deploy smoke test steps (`/health`, `/ready`, Telegram startup visibility, Telegram baseline commands) using portable `grep -E` log filtering in the smoke-test example.

## 5) Known issues
- `git rev-parse --abbrev-ref HEAD` returns `work` in Codex worktree context; per AGENTS.md normalization, branch traceability for this task is carried as declared COMMANDER branch `nwap/execute-deployment-hardening-and-state-sync`.
- `python3 -c "from datetime import datetime; import pytz; ..."` could not run because `pytz` is unavailable in this runner; timestamp derivation used standard library `zoneinfo` for Asia/Jakarta equivalent output.

## 6) What is next
- COMMANDER review of deployment artifact coherence (`Dockerfile`, `fly.toml`, deploy docs) and post-merge truth sync closure.
- If approved, open/continue PR from exact lane `nwap/execute-deployment-hardening-and-state-sync` and preserve paper-only/public-safe boundary language.

Validation Tier   : STANDARD
Claim Level       : FOUNDATION
Validation Target : Post-merge state sync for PR #752 plus deployment artifact coherence across Dockerfile, fly.toml, and directly related deployment documentation
Not in Scope      : Trading logic, risk logic, wallet/account flow, strategy behavior, security-baseline rework, infra redesign, secrets migration, new runtime features, broad doc cleanup
Suggested Next    : COMMANDER review
