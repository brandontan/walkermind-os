# Environment
- Validator role: SENTINEL
- Validation date (Asia/Jakarta): 2026-04-19 05:32
- Repository: `walker-ai-team`
- Project root: `projects/polymarket/polyquantbot`
- PR: #585
- Target branch: `refactor/infra-crusaderbot-fly-readiness-20260419`
- Validation tier: MAJOR
- Claim level: FULL RUNTIME INTEGRATION

# Validation Context
Validated the CrusaderBot Fly.io runtime split against the declared FULL RUNTIME INTEGRATION claim for:
- API control-plane runtime
- deploy entrypoints
- Docker/Fly runtime contract
- startup/health lifecycle surfaces

Out of scope was preserved exactly as declared in the FORGE report.

# Phase 0 Checks
- Forge report exists: `projects/polymarket/polyquantbot/reports/forge/phase7_02_crusaderbot-fly-readiness.md`.
- Forge report includes required MAJOR sections.
- `PROJECT_STATE.md` present with full timestamp.
- Branch traceability uses declared PR branch (`git rev-parse --abbrev-ref HEAD` is `work` in Codex detached mode).
- Static code review completed for all requested files.
- `python -m py_compile` on scoped Python files: PASS.
- `pytest -q projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py`: BLOCKED BY ENV (`fastapi` missing in runner).

# Findings
## F1 — Fly/Docker no longer default to legacy monolithic root main.py (PASS)
- Docker default command is `python projects/polymarket/polyquantbot/scripts/run_api.py`.
- `scripts/run_api.py` imports `projects.polymarket.polyquantbot.server.main:main`.
- No deploy entrypoint currently references `projects/polymarket/polyquantbot/main.py`.

## F2 — API runtime command and import path coherence for container boot (PASS)
- `server/main.py` creates app and launches uvicorn with module path `projects.polymarket.polyquantbot.server.main:app`.
- Host/port are loaded from validated runtime settings.

## F3 — Fly-injected PORT binding (PASS)
- `ApiSettings.from_env()` reads `PORT` and enforces integer + positive constraints.
- `uvicorn.run(..., port=settings.port)` binds to resolved port.

## F4 — /health endpoint and Fly health check compatibility (PASS)
- `/health` route exists in `server/api/routes.py`.
- `fly.toml` health check path is `/health`.
- Docker `HEALTHCHECK` targets `/health`.

## F5 — /ready behavior and startup readiness semantics (CONCERN)
- `/ready` returns 200 only when `RuntimeState.ready` is true and 503 otherwise.
- `ready` is toggled by startup lifecycle (`mark_started`) and shutdown lifecycle (`mark_stopped`).
- This is process-lifecycle readiness, not dependency-readiness (acceptable only if explicitly documented as such).

## F6 — Startup validation deterministic contract (BLOCKER)
- `CRUSADER_STARTUP_MODE` exposes `strict|warn`, but runtime validation path does not implement warning-mode behavior; validation errors still raise and abort startup.
- `validate_api_environment()` includes a port self-comparison that is effectively redundant to prior parsing in `ApiSettings.from_env()`.
- Net effect: startup contract is deterministic but semantically inconsistent with advertised strict/warn mode.

## F7 — Graceful shutdown path (PASS)
- FastAPI lifespan `finally` block calls `run_shutdown(state=state)`.
- Shutdown marks runtime not ready and logs stop event.

## F8 — Telegram bootstrap honesty relative to claim level (FOLLOW-UP, NOT BLOCKER)
- `client/telegram/bot.py` validates env and logs readiness, but exits after `await asyncio.sleep(0)`.
- This is a bootstrap surface, not a sustained Telegram polling/execution loop.
- Claim is acceptable only because task scope names Telegram migration as out of scope; this must remain explicitly non-authoritative for runtime Telegram processing.

## F9 — Documentation/runtime contract drift on readiness checks (BLOCKER)
- `docs/crusader_runtime_surface.md` states readiness checks target `GET /ready`.
- Actual `fly.toml` defines only `/health` checks; no Fly readiness check against `/ready` exists.
- This is deploy-contract overstatement and breaks FULL RUNTIME INTEGRATION truthfulness.

# Score Breakdown
- Deploy entrypoint split correctness: 18/20
- Docker/Fly runtime contract correctness: 14/20
- Startup/health lifecycle fidelity: 14/20
- Claim-level truthfulness and documentation alignment: 10/20
- Test/runtime evidence quality: 12/20

Total: **68/100**

# Critical Issues
1. Startup-mode contract inconsistency (`strict|warn` advertised but warn semantics not implemented in startup validation path).
2. Readiness deploy contract drift (docs claim `/ready` Fly readiness checks, but Fly config only checks `/health`).

# Status
**BLOCKED**

# PR Gate Result
- Merge to target branch is **not recommended** until blockers are fixed and revalidated.
- PR target must remain source-branch flow; never direct-to-main.

# Broader Audit Finding
The API control-plane split is materially in place and deploy entrypoint migration away from root `main.py` is real. However, FULL RUNTIME INTEGRATION claim requires contract-level truthfulness. Current startup-mode semantics and readiness documentation mismatch prevent approval.

# Reasoning
MAJOR + FULL RUNTIME INTEGRATION claims are held to runtime-contract fidelity, not only code presence. Two contract mismatches were found on in-scope surfaces. Because these are correctness/truthfulness gaps (not cosmetic), they are blockers.

# Fix Recommendations
Required before re-run:
1. Implement or remove `warn` startup-mode semantics so behavior matches declared env contract.
2. Align readiness contract between `docs/crusader_runtime_surface.md` and `fly.toml`:
   - either add Fly readiness check path for `/ready`, or
   - update docs to state Fly currently checks `/health` only.
3. Add focused tests for startup-mode behavior and readiness contract assertions.

# Out-of-scope Advisory
- Telegram runtime should eventually move from bootstrap-only surface to sustained event loop/polling runtime when Telegram migration scope is opened.
- Worker runtime remains placeholder-only by declaration and is out of scope for this gate.

# Deferred Minor Backlog
- [DEFERRED] Remove redundant port re-validation in `validate_api_environment()` after startup-mode contract cleanup.

# Telegram Visual Preview
N/A (SENTINEL validation task; no BRIEFER artifact requested).
