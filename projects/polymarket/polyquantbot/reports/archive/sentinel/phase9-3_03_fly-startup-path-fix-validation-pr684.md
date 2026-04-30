# Phase 9.3 — SENTINEL Validation: Fly Startup Path Fix (PR #684)

## Environment
- Timestamp (Asia/Jakarta): 2026-04-21 10:08
- Runner: Codex (`git rev-parse --abbrev-ref HEAD` => `work`)
- Declared source branch: `feature/fix-fly-startup-path-and-redeploy`
- Tooling availability:
  - `flyctl`: not installed (`/bin/bash: flyctl: command not found`)
  - `fly`: not installed (`/bin/bash: fly: command not found`)

## Validation Context
- Tier: MAJOR
- Declared claim: RUNTIME DEPLOY FIX
- Validation target: deploy startup-path fix to Fly and verify live runtime health (`/health`, `/ready`, startup stability, no restart loop).
- Not in scope: strategy logic, wallet lifecycle expansion, release-copy updates, launch assets, live-trading enablement.
- Requested forge source path in task: `projects/polymarket/polyquantbot/reports/forge/phase9-3_05_fly-startup-path-fix.md` (missing in current repository snapshot).

## Phase 0 Checks
- ❌ Required forge source report path from task is missing in repo snapshot.
- ⚠️ Remote branch/PR checkout could not be validated in this runner because no git remote is configured (`git remote -v` empty).
- ⚠️ Fly deploy execution gate unavailable: no Fly CLI present in runner.
- ✅ Static runtime-entry inspection completed for local snapshot:
  - `projects/polymarket/polyquantbot/Dockerfile` CMD points to `projects/polymarket/polyquantbot/scripts/run_api.py`.
  - `projects/polymarket/polyquantbot/fly.toml` HTTP checks target `/health`.
- ✅ Startup/import-risk slice compiles in local snapshot:
  - `python3 -m py_compile` passed for `server/main.py`, `server/api/routes.py`, `server/core/runtime.py`, and `platform/__init__.py`.

## Findings
1. **Live deploy proof could not be executed (blocker).**
   - Deploy to Fly, machine-loop verification, and runtime endpoint probing require Fly CLI and authenticated Fly access.
   - Current runner does not contain Fly CLI binaries (`flyctl`/`fly` missing), so required live checks are not executable here.

2. **Task-referenced forge report path is missing (traceability blocker).**
   - The required source report `phase9-3_05_fly-startup-path-fix.md` is absent in this repo snapshot.
   - Available related forge report is `projects/polymarket/polyquantbot/reports/forge/phase9-1_07_fly-startup-platform-shadow-hotfix.md`, which does not match requested source-path identity for PR #684 validation.

3. **Local static contract appears internally consistent but is insufficient for MAJOR runtime approval.**
   - `Dockerfile` entrypoint points to `scripts/run_api.py`, which delegates to `server.main:main()`.
   - API routes expose `/health` and `/ready` with readiness semantics tied to runtime state and startup validation.
   - These checks are code-level only and do not prove live Fly machine behavior.

## Score Breakdown
- Traceability readiness: 10/25 (source report mismatch)
- Deployment evidence: 0/35 (Fly deploy not executable in runner)
- Runtime health evidence: 0/25 (`/health` + `/ready` not validated against live Fly app)
- Static contract integrity: 15/15 (local code path compiles and route contracts exist)
- **Total: 25/100**

## Critical Issues
- C1: Missing required source report path from task (`phase9-3_05_fly-startup-path-fix.md`).
- C2: No live Fly deployment/runtime evidence collected for PR #684 due unavailable Fly CLI in this runner.

## Status
**BLOCKED**

## PR Gate Result
- Verdict: **BLOCKED**
- Merge recommendation: **Do not merge** until deployment/runtime evidence is captured from a Fly-capable lane and attached to this validation lane.

## Broader Audit Finding
- No contradiction found in local startup-path code slice, but MAJOR-tier runtime proof remains absent.

## Reasoning
- MAJOR validation claim requires live deployment and runtime-machine health proof.
- Without deploy execution and endpoint probes against running Fly machine(s), SENTINEL cannot assert startup-path fix effectiveness in production-like runtime.
- Safe-default mode applies: insufficient proof => blocked verdict.

## Fix Recommendations
1. Run SENTINEL rerun in a Fly-capable environment with authenticated Fly CLI.
2. Validate the exact source artifact path for PR #684 (or provide corrected forge source path if renamed).
3. Capture and include:
   - `flyctl deploy` output for the target branch/app,
   - machine status showing no restart loop,
   - `curl` responses for `/health` and `/ready`,
   - startup logs proving deployed entrypoint path aligns with Dockerfile/fly.toml fix.

## Out-of-scope Advisory
- None beyond declared exclusions.

## Deferred Minor Backlog
- None.

## Telegram Visual Preview
- PR #684 SENTINEL runtime gate: **BLOCKED (25/100)**.
- Blockers: missing required forge source path + no Fly deploy/runtime evidence in this runner.
- Next: rerun validation in Fly-capable environment with deploy logs and `/health` + `/ready` proof.
