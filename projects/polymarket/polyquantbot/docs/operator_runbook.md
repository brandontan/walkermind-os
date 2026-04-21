# CrusaderBot Operator Runbook (Paper Beta)

## 1) Runtime truth (current posture)

- Public-ready **paper beta** posture is active.
- Runtime is paper-only; no live-trading claims are allowed.
- Fly runtime and Telegram runtime/code path are landed.
- Sentry integration is landed in code; first-event proof can still require runtime verification.
- Product is **not** live-trading ready and **not** production-capital ready.

## 2) First checks after any restart/redeploy

1. Root endpoint (`/`) for service reachability.
2. `/health` for process-level health.
3. `/ready` for dependency/runtime readiness (including Telegram runtime truth).
4. Telegram baseline commands: `/start`, `/help`, `/status`.
5. Fly logs for startup, polling, and error signals.

## 3) Interpreting `/health`

- Use `/health` as a **process/aliveness** signal.
- Expected operator interpretation:
  - `200 OK` means app process is up and responding.
  - Non-200/timeouts mean runtime incident; check Fly machine state + logs immediately.
- Do not treat `/health` alone as full runtime readiness.

## 4) Interpreting `/ready`

- Use `/ready` as **operational readiness** signal.
- Expected operator interpretation:
  - `ready=true` (or equivalent all-green state) means runtime dependencies are currently in expected state.
  - Degraded/not-ready means runtime may answer HTTP but is not operationally ready.
- `/ready` should be checked together with logs and Telegram command behavior.

## 5) Paper-only boundary (operational meaning)

Paper-only means:

- No real-money order execution.
- No production-capital exposure claims.
- Public messaging must keep paper-beta limitations explicit.
- Any capital/live-trading wording escalation requires a separate validated lane.

## 6) Public-safe claim boundaries

Safe to claim publicly now:

- Public-ready paper beta posture.
- Runtime endpoints and Telegram baseline command availability (when currently verified).
- Paper-only boundary and non-production readiness posture.

Not safe to claim publicly:

- Live-trading readiness.
- Production-capital readiness.
- Guaranteed uptime/performance beyond verified evidence window.
