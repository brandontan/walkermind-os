# FORGE-X Report — phase11-1_01_deployment-hardening-and-truth-sync

- Timestamp: 2026-04-23 21:58 (Asia/Jakarta)
- Branch: feature/phase11-1-deployment-hardening
- Scope lane: Phase 11.1 deployment hardening + repo-truth sync after merged-main Phase 10.9 security baseline completion

## 1) What was built
- Synced roadmap/checklist truth to merged-main status for Phase 10.9 security baseline hardening (PR #742) and normalized next lane naming to Phase 11.1 deployment hardening.
- Hardened deployment contract in Docker runtime image:
  - startup command aligned to `python3 -m projects.polymarket.polyquantbot.scripts.run_api`
  - removed dependency on runtime `curl` by switching container healthcheck probe to Python stdlib HTTP call against `/health`
  - set unbuffered Python runtime env and created writable runtime path for `/tmp/crusaderbot/runtime`
- Hardened Fly runtime availability contract:
  - set `auto_stop_machines='off'` and `min_machines_running=1` for polling/runtime continuity
  - added `/ready` HTTP service check and rolling deploy strategy
- Added deployment contract tests covering Docker entrypoint/healthcheck truth and Fly availability/readiness truth.
- Added explicit rollback + post-deploy smoke contract guidance to Fly runtime troubleshooting runbook.

## 2) Current system architecture (relevant slice)
- Deploy runtime process model:
  - Container command -> `python3 -m projects.polymarket.polyquantbot.scripts.run_api`
  - `run_api` invokes `projects.polymarket.polyquantbot.server.main:main()`
  - Uvicorn serves FastAPI control-plane with `/health` (liveness) and `/ready` (runtime readiness)
- Health/readiness contract:
  - Docker image-level `HEALTHCHECK` probes `/health`
  - Fly service-level check probes `/ready`
  - Runtime remains paper-only boundary; no live-trading authority claim added
- Availability/restart posture:
  - Fly keeps one machine running continuously for Telegram polling compatibility
  - Deploy strategy is rolling for safer release transition

## 3) Files created / modified (full repo-root paths)
- `projects/polymarket/polyquantbot/Dockerfile`
- `projects/polymarket/polyquantbot/fly.toml`
- `projects/polymarket/polyquantbot/tests/test_phase11_1_deploy_runtime_contract.py`
- `projects/polymarket/polyquantbot/docs/fly_runtime_troubleshooting.md`
- `projects/polymarket/polyquantbot/work_checklist.md`
- `ROADMAP.md`
- `PROJECT_STATE.md`
- `projects/polymarket/polyquantbot/reports/forge/phase11-1_01_deployment-hardening-and-truth-sync.md`

## 4) What is working
- Repo-truth drift is closed for Phase 10.9 status across roadmap + project checklist references.
- Phase numbering normalization to 11.1 is reflected in active lane planning text.
- Dockerfile and fly.toml now align to the actual runtime process and readiness surfaces.
- Deploy/runtime contract test coverage exists for the touched deployment surfaces.
- Rollback and post-deploy smoke expectations are documented for operator execution continuity.

## 5) Known issues
- Staging/prod remote deploy evidence (`/health`, `/ready`, and Fly logs) is not executed from this local run and remains required for SENTINEL MAJOR gate closure.

## 6) What is next
- Required next gate: SENTINEL MAJOR validation over Phase 11.1 deploy/runtime hardening lane.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Fly + Docker deploy/runtime hardening contract and Phase 10.9 -> Phase 11.1 repo-truth sync
Not in Scope      : live-trading authority, production-capital readiness, strategy/runtime trading logic expansion, wallet lifecycle expansion, unrelated UX copy cleanup
Suggested Next    : SENTINEL validation on branch `feature/phase11-1-deployment-hardening`
