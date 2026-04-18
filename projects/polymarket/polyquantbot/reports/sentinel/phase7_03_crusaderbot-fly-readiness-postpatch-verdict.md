# Environment
- Validator role: SENTINEL
- Validation date (Asia/Jakarta): 2026-04-19 06:26
- Repository: `walker-ai-team`
- Project root: `projects/polymarket/polyquantbot`
- PR: #585
- Target branch: `refactor/infra-crusaderbot-fly-readiness-20260419`
- Validation tier: MAJOR
- Claim level: FULL RUNTIME INTEGRATION

# Validation Context
This run supersedes stale BLOCKED context and validates patched PR #585 surfaces directly, with priority on prior blockers:
1. startup-mode contract mismatch
2. `/ready` vs Fly health/readiness documentation drift

Scope validated from patched branch:
- `projects/polymarket/polyquantbot/server/core/runtime.py`
- `projects/polymarket/polyquantbot/client/telegram/bot.py`
- `projects/polymarket/polyquantbot/docs/crusader_runtime_surface.md`
- `projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py`
- `projects/polymarket/polyquantbot/reports/forge/phase7_02_crusaderbot-fly-readiness.md`
plus deploy/runtime coherence checks on `fly.toml`, `Dockerfile`, `server/main.py`, and `server/api/routes.py`.

# Phase 0 Checks
- Required source reports present (`phase7_01` blocked report and `phase7_02` revalidation report).
- Forge report path present and aligned with target task (`phase7_02`).
- `python -m py_compile` on scoped files: PASS.
- `pytest -q projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py`: ENV-LIMITED (missing `fastapi`).
- Attempt to install test dependency (`pip install fastapi uvicorn[standard]`): ENV-LIMITED (proxy 403 in runner).

# Findings
## F1 — Startup-mode blocker resolution (PASS)
- `ApiSettings.from_env()` now enforces strict-only startup mode (`CRUSADER_STARTUP_MODE` must be `strict`).
- `TelegramBotSettings.from_env()` enforces the same strict-only contract.
- No fake warn semantics are exposed in patched runtime surfaces.

## F2 — Readiness contract blocker resolution (PASS)
- Runtime docs state Fly checks `/health` only.
- Docs explicitly treat `/ready` as API endpoint, not active Fly probe.
- `fly.toml` remains configured with `path = "/health"`, matching docs.

## F3 — No blocker-level regression on runtime contract (PASS)
- Docker runtime command still targets API split entrypoint.
- `/health` endpoint exists and aligns with Fly probe path.
- `/ready` endpoint still exists and reports runtime-ready truth from state.
- Graceful shutdown path remains in FastAPI lifespan teardown.

## F4 — Claim/report alignment on patched branch (PASS)
- Forge report wording now matches strict-only startup contract and `/health` Fly probe truth.
- No new blocker-level overstatement found in scoped runtime/deploy contract claims.

# Score Breakdown
- Startup contract correctness: 20/20
- Readiness/deploy contract alignment: 20/20
- Regression check on runtime lifecycle surfaces: 19/20
- Claim/report truthfulness: 19/20
- Executable validation evidence in current runner: 11/20

Total: **89/100**

# Critical Issues
- None.

# Status
**CONDITIONAL**

# PR Gate Result
- Blocker-level findings from prior BLOCKED verdict are resolved.
- Merge may proceed at COMMANDER discretion under CONDITIONAL status.
- Condition: attach successful execution output of
  `pytest -q projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py`
  from CI/local environment where FastAPI dependency is available.

# Broader Audit Finding
Patched PR #585 is no longer blocked on contract mismatch. Remaining limitation is runner dependency availability, not code/deploy-contract drift.

# Reasoning
This validation targets patched code directly and confirms both previous blocker classes are closed. The verdict remains CONDITIONAL because executable runtime tests could not be run in this environment due dependency/network constraints.

# Fix Recommendations
- Non-blocking evidence closure: run scoped pytest in dependency-complete CI and link output to PR #585.

# Out-of-scope Advisory
- Telegram migration depth and worker orchestration remain unchanged and out of scope for this validation pass.

# Deferred Minor Backlog
- [DEFERRED] Codex runner package/proxy limitation prevents FastAPI test dependency installation for local evidence capture.

# Telegram Visual Preview
N/A (SENTINEL report artifact only; BRIEFER not requested).
