# FORGE-X Report — phase11-1_01_deploy-hardening-clean-rebuild

- Timestamp: 2026-04-24 02:22 (Asia/Jakarta)
- Branch: feature/phase11-1-deploy-hardening (local target)
- Scope lane: clean Phase 11.1 deployment/runtime rebuild plus PR #750 rehome truth-sync attempt

## 1) What was built
- Verified exact GitHub truth: PR #750 is currently open on head `feature/restart-phase-11.1-deployment-hardening`.
- Attempted compliant-branch rehome actions (create ref, create replacement PR, close PR #750), but all write endpoints returned HTTP 403 `Method forbidden` in this runner.
- Rebuilt the Phase 11.1 deployment/runtime contract on AGENTS-compliant branch `feature/phase11-1-deploy-hardening`.
- Hardened container contract in `projects/polymarket/polyquantbot/Dockerfile`:
  - runtime copy layout set to `COPY . /app`
  - startup command set to `python3 -m projects.polymarket.polyquantbot.scripts.run_api`
  - runtime healthcheck moved from `curl` to Python stdlib HTTP probe against `/health`
  - `PYTHONDONTWRITEBYTECODE` and `PYTHONUNBUFFERED` enabled
- Hardened Fly runtime contract in `projects/polymarket/polyquantbot/fly.toml`:
  - `auto_stop_machines = 'off'`
  - `min_machines_running = 1`
  - `/ready` service check added
  - rolling deploy strategy declared
- Added deploy/runtime contract tests in `projects/polymarket/polyquantbot/tests/test_phase11_1_deploy_runtime_contract.py`.
- Added rollback and post-deploy smoke guidance to `projects/polymarket/polyquantbot/docs/fly_runtime_troubleshooting.md`.
- Synced `PROJECT_STATE.md`, `ROADMAP.md`, and `projects/polymarket/polyquantbot/work_checklist.md` to exact current PR #750 truth while preserving the compliant-branch rehome target and without reviving PR #748/#749 storyline.

## 2) Current system architecture (relevant slice)
- Runtime process entrypoint is `python3 -m projects.polymarket.polyquantbot.scripts.run_api`.
- `scripts/run_api.py` now uses lazy import so module import stays lightweight while runtime execution still calls server main.
- Docker image-level healthcheck probes `/health`; Fly service check probes `/ready`.
- Fly availability settings keep one running machine for runtime/polling stability.

## 3) Files created / modified (full repo-root paths)
- `projects/polymarket/polyquantbot/Dockerfile`
- `projects/polymarket/polyquantbot/fly.toml`
- `projects/polymarket/polyquantbot/scripts/run_api.py`
- `projects/polymarket/polyquantbot/tests/test_phase11_1_deploy_runtime_contract.py`
- `projects/polymarket/polyquantbot/docs/fly_runtime_troubleshooting.md`
- `PROJECT_STATE.md`
- `ROADMAP.md`
- `projects/polymarket/polyquantbot/work_checklist.md`
- `projects/polymarket/polyquantbot/reports/forge/phase11-1_01_deploy-hardening-clean-rebuild.md`

## 4) What is working
- Deploy/runtime contract is internally consistent across Docker WORKDIR, copy layout, and module entrypoint.
- `projects.polymarket.polyquantbot.scripts.run_api` imports cleanly after lazy-import wrapper.
- Scoped py_compile and pytest checks for this lane pass.

## 5) Known issues
- GitHub write operations are blocked in this runner (HTTP 403 `Method forbidden`), so replacement PR creation and PR #750 closure could not be completed here.
- Remote Fly staging/prod smoke evidence is not executed in this local run and remains required for SENTINEL MAJOR gate closure.

## 6) What is next
- Publish `feature/phase11-1-deploy-hardening` and open replacement PR to `main` from an authenticated environment.
- Close PR #750 only after replacement PR confirmation.
- COMMANDER review, then SENTINEL MAJOR validation on the replacement PR.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : deploy/runtime contract consistency across Dockerfile, fly.toml, run_api entrypoint, and scoped tests
Not in Scope      : replacement-PR storyline, unrelated deployment feature expansion, strategy/risk/execution logic changes
Suggested Next    : COMMANDER executes authenticated PR rehome flow, then SENTINEL MAJOR validation on the replacement PR
