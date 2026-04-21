# Phase 9.3 — Fly Startup Path Fix and Redeploy Attempt (Blocked by Environment Access)

**Date:** 2026-04-21 09:57
**Branch:** feature/fix-fly-startup-path-and-redeploy
**Task:** Fix Fly startup crash from invalid runtime entry path, redeploy, and verify runtime health (`/health`, `/ready`, machine stability).

## 1. What was built

- Fixed container runtime path mismatch by copying project files into `/app/projects/polymarket/polyquantbot` in the image so the `projects.polymarket...` import tree and path expectations are valid at runtime.
- Switched runtime entry invocation to module form (`python -m projects.polymarket.polyquantbot.scripts.run_api`) to avoid script-path `sys.path` import failure mode.
- Added explicit Fly process command in `fly.toml` so process startup is pinned to the corrected module entrypoint.
- Captured fresh runtime/deploy evidence in `projects/polymarket/polyquantbot/reports/forge/phase9-3_05_fly-runtime-evidence.log`.

## 2. Current system architecture (relevant slice)

1. Fly app `crusaderbot` runs process `app` from `projects/polymarket/polyquantbot/fly.toml`.
2. Container image now materializes project code under `/app/projects/polymarket/polyquantbot`.
3. Runtime process command is module-based (`python -m projects.polymarket.polyquantbot.scripts.run_api`) and resolves through the existing `projects.polymarket.polyquantbot.server.main` runtime entry.
4. Health endpoints remain defined in API route surface (`/health`, `/ready`) and are expected to be validated externally after deploy.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/polyquantbot/Dockerfile`
- `projects/polymarket/polyquantbot/fly.toml`
- `projects/polymarket/polyquantbot/reports/forge/phase9-3_05_fly-startup-path-fix.md`
- `projects/polymarket/polyquantbot/reports/forge/phase9-3_05_fly-runtime-evidence.log`

## 4. What is working

- Startup command/path mismatch is corrected in source for both Docker default command and Fly `processes.app` command.
- Module execution now advances past previous missing-file failure mode; local sanity now fails later at missing dependency (`uvicorn`) in this runner, indicating path/module resolution is fixed and failure moved beyond original crash class.
- Evidence artifact captures branch identity, changed startup directives, local module-launch output, deploy attempt output, and live endpoint probe outputs.

## 5. Known issues

- **Blocker:** this runner cannot execute Fly redeploy because `flyctl` is not available and cannot be installed here (install endpoint access fails with HTTP 403 in this environment).
- **Blocker:** external probes to `https://crusaderbot.fly.dev/health` and `/ready` remain blocked by CONNECT tunnel `403 Forbidden (envoy)`, so live post-fix runtime status cannot be verified from this runner.
- Because deploy + live health checks are externally blocked, this task is closed as **NEXT BLOCKER** rather than PASS.

## 6. What is next

- Run deploy from a Fly-accessible environment with authenticated `flyctl` on this branch head, using `projects/polymarket/polyquantbot/fly.toml`.
- Validate machine stability (no restart loop) and confirm `GET /health` + `GET /ready` from Fly-visible network.
- Send this branch to SENTINEL for MAJOR-tier verification after deploy evidence is produced.

Validation Tier   : MAJOR
Claim Level       : RUNTIME DEPLOY FIX
Validation Target : Fix runtime startup path/entrypoint mismatch and re-verify deployed machine health (`/health`, `/ready`, restart-loop status)
Not in Scope      : strategy logic, risk constants, wallet lifecycle expansion, release copy/docs refresh, live-trading enablement
Suggested Next    : SENTINEL validation on actual PR head branch after Fly-accessible deploy evidence capture
