# Sentry 01 — Python Runtime Validation (PR #700)

Environment
- Date (Asia/Jakarta): 2026-04-21 22:18
- Validator Role: SENTINEL
- Validation Tier: MAJOR
- Claim Level (task-declared): OBSERVABILITY / ERROR REPORTING
- Source branch (task-declared): `feature/integrate-sentry-python-runtime`
- Source forge report: `projects/polymarket/polyquantbot/reports/forge/sentry_01_python-runtime-integration.md`
- Runner constraints observed: outbound probes to `crusaderbot.fly.dev` blocked by CONNECT tunnel `403`; `flyctl` unavailable in runner.

Validation Context
- Objective: Validate deployed Python Sentry integration for FastAPI runtime and Telegram/runtime handled-exception capture using env-only `SENTRY_DSN`.
- In-scope checks executed against code + local test surface + reachable network surface:
  - Env-driven integration wiring (`SENTRY_DSN`) and no hardcoded DSN posture.
  - FastAPI startup integration call path and handled-exception capture hooks.
  - Health/readiness endpoint reachability from this runner.
  - Runtime/test evidence for `send_default_pii=False` and checklist truth sync.
- Not in scope preserved: Node SDK integration, dashboard rollout, observability redesign, Telegram UX changes, live-trading enablement.

Phase 0 Checks
- Forge report exists at required path: PASS.
- Forge report includes MAJOR six-section structure: PASS.
- PROJECT_STATE.md contains full timestamp format: PASS (`Last Updated : 2026-04-21 22:18`).
- Required local compile check rerun:
  - `PYTHONIOENCODING=utf-8 python3 -m py_compile projects/polymarket/polyquantbot/server/core/sentry_runtime.py projects/polymarket/polyquantbot/server/main.py projects/polymarket/polyquantbot/client/telegram/runtime.py projects/polymarket/polyquantbot/tests/test_sentry_runtime_integration_20260421.py` -> PASS.
- Targeted pytest rerun:
  - `PYTHONIOENCODING=utf-8 pytest -q projects/polymarket/polyquantbot/tests/test_sentry_runtime_integration_20260421.py` -> WARNING (`1 skipped`) due missing runtime dependency surface in this environment.

Findings
1) `SENTRY_DSN` consumption is implemented in Python runtime
- Evidence:
  - `initialize_sentry()` reads DSN via `os.getenv("SENTRY_DSN", "").strip()` and disables integration if missing.
  - `create_app()` invokes `initialize_sentry()` before app creation.
- Result: PASS (code-level).

2) Fly secret naming requirement (`SENTRY_DSN`) in deployed environment
- Evidence:
  - Code consumes `SENTRY_DSN` (required secret/env name).
  - `flyctl` unavailable (`which flyctl || which fly` returned non-zero), so deployed secret inventory cannot be queried from this runner.
- Result: INCONCLUSIVE (deployment secret presence could not be directly verified).

3) `/health` and `/ready` runtime checks on deployed target
- Evidence:
  - `curl -i --max-time 20 https://crusaderbot.fly.dev/health` -> `HTTP/1.1 403 Forbidden` with `curl: (56) CONNECT tunnel failed`.
  - `curl -i --max-time 20 https://crusaderbot.fly.dev/ready` -> same proxy tunnel `403` failure.
- Result: FAIL (no reachable deploy proof from this runner).

4) No startup crash introduced by Sentry integration
- Evidence:
  - Compile checks passed.
  - Forge-intended runtime tests present, but targeted pytest skipped in this environment.
- Result: PARTIAL PASS (static/code path healthy; runtime boot proof unavailable here).

5) Controlled Sentry event / meaningful runtime exception reaches Sentry
- Evidence:
  - Runtime exception hooks are present (`capture_runtime_exception(...)`) across Telegram/runtime handled-exception paths.
  - No deploy-connected DSN/event pipeline was reachable; no Sentry event ID or dashboard receipt evidence provided in this validation run.
- Result: FAIL (required deployment event proof missing).

6) DSN hardcode scan
- Evidence:
  - No production DSN hardcode found in runtime code paths; DSN comes from env access.
- Result: PASS.

7) PII posture (`send_default_pii=False`)
- Evidence:
  - Sentry init sets `send_default_pii=False`.
  - Test asserts this behavior.
- Result: PASS.

8) Telegram/runtime capture-hook flood/noise posture
- Evidence:
  - Hooks are attached only within exception handlers; they forward handled exceptions with surface tags.
  - No dedupe/throttle mechanism observed in helper itself.
  - No deploy log or Sentry volume evidence available to assess real-world noise/flood behavior.
- Result: CONDITIONAL (wiring is sensible but operational-noise proof not demonstrated).

9) `work_checklist.md` truth sync
- Evidence:
  - Checklist line reflects implemented Sentry runtime wiring and exception surfaces.
- Result: PASS (code/report consistency).

Score Breakdown
- Code wiring and posture checks: 34/40
- Runtime/deploy health checks: 8/25
- Event-delivery proof: 0/20
- Documentation/checklist truth: 10/10
- Safety/noise posture confidence: 3/5
- Total: 55/100

Critical Issues
1. Missing deploy runtime reachability proof for `/health` and `/ready` from validation runner.
2. Missing hard evidence of successful Sentry event ingestion (event ID or dashboard receipt) under deployed DSN.
3. Fly secret presence (`SENTRY_DSN`) could not be directly verified in deploy environment due missing Fly CLI access in this runner.

Status
- Verdict: BLOCKED
- Rationale: Mandatory deploy/runtime evidence checks remain unproven; MAJOR gate cannot be approved on code-only validation.

PR Gate Result
- PR #700 gate: BLOCKED
- Merge recommendation: Do not merge until deploy evidence is attached for secret presence, endpoint health, and at least one confirmed Sentry event.

Broader Audit Finding
- Integration quality at code level is clean and bounded (env-only DSN + no-op fallback + explicit exception capture).
- Remaining risk is purely evidence/runtime verification gap, not an immediate code defect.

Reasoning
- This MAJOR validation requires proof on deployed runtime behavior, not only implementation presence.
- Inability to verify live health/readiness and Sentry event delivery prevents confidence that integration works in real Fly runtime conditions.

Fix Recommendations
1. Run validation in a network path that can reach `https://crusaderbot.fly.dev` without proxy tunnel denial.
2. In Fly environment, confirm secret exists with exact key name `SENTRY_DSN` and redeploy/restart app.
3. Trigger one controlled handled exception in Telegram/runtime path and attach Sentry event receipt evidence (event ID, timestamp, environment/release tags).
4. Re-run `/health` and `/ready` probes post-deploy and attach command output.
5. Add temporary operator-safe event marker/tag for one controlled validation event to simplify confirmation and avoid noisy repeats.

Out-of-scope Advisory
- Node SDK integration and alert/dashboard policy are intentionally out of scope and should be tracked in separate observability lanes.

Deferred Minor Backlog
- Consider adding optional sampling/guardrail controls for handled runtime exception bursts to reduce potential duplicate reporting under repeated failure loops.

Telegram Visual Preview
- N/A (this validation task is backend observability/runtime gate verification and did not require Telegram UI copy transformation artifacts).
