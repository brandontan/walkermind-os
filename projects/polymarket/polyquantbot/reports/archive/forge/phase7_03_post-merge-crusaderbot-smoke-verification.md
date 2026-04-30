# FORGE-X Report — Phase 7.3 Post-Merge CrusaderBot Smoke Verification on Main

## 1) What was built
- Executed a post-merge smoke verification pass on `main` for the CrusaderBot Fly-readiness runtime split scope, focusing on entrypoint continuity, Fly contract continuity, FastAPI boot contract continuity, endpoint contract presence, and truth alignment across runtime files, docs, and state artifacts.
- Verified static runtime/deploy contract coherence between Docker command path, API entrypoint resolver, FastAPI lifecycle + strict startup guard, Fly `/health` probe contract, and `/ready` lifecycle endpoint contract.
- Verified main-branch truth alignment against `PROJECT_STATE.md` and the merged SENTINEL artifact path `projects/polymarket/polyquantbot/reports/sentinel/phase7_02_crusaderbot-fly-readiness-revalidation.md`.

## 2) Current system architecture (relevant slice)
- Deploy/runtime entrypoint chain remains:
  - Docker `CMD` -> `projects/polymarket/polyquantbot/scripts/run_api.py`
  - `scripts/run_api.py` -> `projects.polymarket.polyquantbot.server.main:main`
  - `server/main.py` constructs FastAPI app, applies lifespan startup/shutdown hooks, and runs uvicorn using resolved `ApiSettings`.
- Fly contract remains aligned to the API surface:
  - `fly.toml` uses `internal_port = 8080` and HTTP health check path `/health`.
  - Docker image also uses `/health` for container healthcheck.
- Runtime lifecycle contract remains strict:
  - API reads Fly-injected `PORT` from env and enforces strict-only `CRUSADER_STARTUP_MODE`.
  - Graceful shutdown path remains implemented via `run_shutdown(...)` in lifespan finalizer.
  - `/ready` returns truthful lifecycle state (`200 ready` or `503 not_ready`) and is documented as a lifecycle visibility route, not Fly's health probe.

## 3) Files created / modified (full repo-root paths)
- `projects/polymarket/polyquantbot/reports/forge/phase7_03_post-merge-crusaderbot-smoke-verification.md` (new)
- `PROJECT_STATE.md` (updated post-merge smoke lane truth)

## 4) What is working
- Entrypoint continuity: PASS.
  - Docker still targets `projects/polymarket/polyquantbot/scripts/run_api.py`.
  - API script still resolves to `projects.polymarket.polyquantbot.server.main:main`.
- Fly contract continuity: PASS.
  - Fly health probe remains `/health`.
  - No code/docs claim that Fly probes `/ready`; docs explicitly state `/ready` is exposed but not configured as Fly health probe.
  - Internal port remains `8080`, aligned with runtime default/app boot expectations.
- FastAPI boot continuity: PASS (contract-level).
  - App reads env `PORT`, startup mode remains strict-only, and shutdown path remains explicit.
- Endpoint surface contract continuity: PASS (code + tests + docs alignment).
  - `/health` route exists and returns success contract payload.
  - `/ready` route exists and returns lifecycle/readiness truth contract with status code differentiation.
  - Runtime code, Dockerfile, fly.toml, docs, and dedicated runtime test file remain coherent for this lane.

## 5) Known issues
- Environment limitation during verification runner execution:
  - `pytest -q projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py` could not execute because `fastapi` is unavailable in the current runner and outbound package install is blocked by network/proxy restrictions.
  - This is a verification-environment constraint, not a detected runtime drift in repository code.
- Existing non-runtime warning continuity remains unchanged:
  - Pytest warning `Unknown config option: asyncio_mode` still appears in current test tooling context.

## 6) What is next
- Recommended next lane under COMMANDER: proceed to the next roadmap implementation slice after this smoke continuity confirmation.
- If COMMANDER requests deeper runtime proof before deployment promotion, run the same smoke checks in a dependency-complete CI/deploy-parity environment and capture live HTTP probe evidence.

Validation Tier   : MAJOR
Claim Level       : POST-MERGE RUNTIME CONTINUITY
Validation Target : Entrypoint/Fly/FastAPI boot/endpoint and truth alignment continuity on merged `main` CrusaderBot Fly-readiness runtime split
Not in Scope      : New runtime refactor, infra migration, risk/execution logic expansion, phase restructuring
Suggested Next    : COMMANDER review; optional SENTINEL deep runtime confirmation if deployment gate demands live parity evidence
