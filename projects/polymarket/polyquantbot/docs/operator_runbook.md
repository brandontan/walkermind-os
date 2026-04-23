# CrusaderBot Operator Runbook (Paper Beta)

## 1) Runtime truth (current posture)

- Public-ready **paper beta** posture is active.
- Runtime is paper-only; no live-trading claims are allowed.
- Fly runtime deploys a **single API machine** with embedded Telegram polling startup in the same process lifecycle.
- Sentry integration is landed in code; first-event proof can still require runtime verification.
- Product is **not** live-trading ready and **not** production-capital ready.

## 2) Restart policy truth (Fly deployment contract)

- Fly machine count is pinned to one (`min_machines_running=1`, `max_machines_running=1`).
- `auto_stop_machines="off"` keeps the machine resident instead of scale-to-zero shutdown.
- Fly health check gates process health on `GET /health`; readiness visibility is provided by `GET /ready`.
- Expected operator posture: if `/health` fails or startup crashes, Fly restarts the machine; operator still validates readiness and Telegram startup logs after restart.

## 3) First checks after any restart/redeploy

1. Root endpoint (`/`) for service reachability.
2. `/health` for process-level health.
3. `/ready` for dependency/runtime readiness (including Telegram runtime truth).
4. Telegram baseline commands: `/start`, `/help`, `/status`.
5. Fly logs for startup, polling, and error signals.

## 4) Interpreting `/health`

- Use `/health` as a **process/aliveness** signal.
- Expected operator interpretation:
  - `200 OK` means app process is up and responding.
  - Non-200/timeouts mean runtime incident; check Fly machine state + logs immediately.
- Do not treat `/health` alone as full runtime readiness.

## 5) Interpreting `/ready`

- Use `/ready` as **operational readiness** signal.
- Expected operator interpretation:
  - `ready=true` (or equivalent all-green state) means runtime dependencies are currently in expected state.
  - Degraded/not-ready means runtime may answer HTTP but is not operationally ready.
- `/ready` should be checked together with logs and Telegram command behavior.

## 6) Rollback procedure truth (bounded)

Use rollback when a new deploy regresses `/health`, `/ready`, or Telegram startup visibility.

1. Identify last known good release:
   - `fly releases -a crusaderbot`
2. Roll back to that release:
   - `fly releases rollback <RELEASE_ID> -a crusaderbot`
3. Re-run post-deploy smoke checks (Section 7) before declaring restored service.
4. Record rollback reason and failing signal (`/health`, `/ready`, or Telegram startup evidence) in task/report continuity.

## 7) Post-deploy smoke test (public-safe baseline)

Run immediately after deploy or rollback:

1. `curl -fsS https://crusaderbot.fly.dev/health`
2. `curl -fsS https://crusaderbot.fly.dev/ready`
3. `fly logs -a crusaderbot | grep -E "crusaderbot_telegram_runtime_started|crusaderbot_runtime_transition"`
4. Baseline command sanity in Telegram chat: `/start`, `/help`, `/status`

Pass condition (bounded scope):
- `/health` returns success.
- `/ready` returns operational readiness payload.
- Logs show runtime startup transition and Telegram runtime startup visibility.
- Telegram baseline commands return non-empty public-safe responses.

## 8) Paper-only boundary (operational meaning)

Paper-only means:

- No real-money order execution.
- No production-capital exposure claims.
- Public messaging must keep paper-beta limitations explicit.
- Any capital/live-trading wording escalation requires a separate validated lane.

## 9) Public-safe claim boundaries

Safe to claim publicly now:

- Public-ready paper beta posture.
- Runtime endpoints and Telegram baseline command availability (when currently verified).
- Paper-only boundary and non-production readiness posture.

Not safe to claim publicly:

- Live-trading readiness.
- Production-capital readiness.
- Guaranteed uptime/performance beyond verified evidence window.
