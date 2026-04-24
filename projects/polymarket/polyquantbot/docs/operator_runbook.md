# CrusaderBot Operator Runbook (Paper Beta)

## 1) Runtime truth (current posture)

- Public-ready **paper beta** posture is active.
- Runtime is paper-only; no live-trading claims are allowed.
- Fly runtime deploys a **single API machine** with embedded Telegram polling startup in the same process lifecycle.
- Deployment contract is defined by `projects/polymarket/polyquantbot/Dockerfile` + `projects/polymarket/polyquantbot/fly.toml`.
- Product is **not** live-trading ready and **not** production-capital ready.

## 2) Authoritative deployment/startup contract

- Container entrypoint: `python -m projects.polymarket.polyquantbot.scripts.run_api`.
- Container aliveness contract: Docker `HEALTHCHECK` calls `GET /health` on `127.0.0.1:$PORT`.
- Fly machine contract:
  - single machine pinned (`min_machines_running=1`, `max_machines_running=1`),
  - no scale-to-zero (`auto_stop_machines="off"`),
  - startup health gate on `GET /health`,
  - operational readiness gate on `GET /ready`,
  - deployment strategy `immediate` to avoid overlapping Telegram pollers.

## 3) Restart policy truth (operator-facing)

- Restart expectation: Fly restarts the machine when process/aliveness checks fail.
- Operator expectation after any restart:
  1. Re-check `/health`.
  2. Re-check `/ready`.
  3. Verify Telegram runtime startup logs.
  4. Verify Telegram baseline commands still respond.

## 4) Rollback procedure truth (bounded)

Use rollback when a new deploy regresses `/health`, `/ready`, or Telegram startup visibility.

1. Identify the last known-good image:
   - `fly releases --app crusaderbot --image`
2. Redeploy that exact image:
   - `fly deploy --image registry.fly.io/crusaderbot:<IMAGE_TAG> --strategy immediate`
3. Run post-deploy smoke tests (Section 5).
4. Record rollback cause and failed signals (`/health`, `/ready`, startup logs, command behavior).
5. Reconcile any config, secret, or `fly.toml` drift manually; image rollback does not revert those automatically.

## 5) Post-deploy smoke test contract

Run immediately after deploy/restart/rollback:

1. `curl -fsS https://crusaderbot.fly.dev/health`
2. `curl -fsS https://crusaderbot.fly.dev/ready`
3. `fly logs -a crusaderbot | grep -E "crusaderbot_telegram_runtime_started|crusaderbot_runtime_transition"`
4. Telegram command checks: `/start`, `/help`, `/status`

Pass condition (bounded scope):
- `/health` returns success,
- `/ready` returns ready payload,
- startup/transition logs are present,
- baseline Telegram commands return non-empty public-safe replies.

## 6) Readiness interpretation rules

- `/health` confirms process aliveness only.
- `/ready` confirms runtime/dependency readiness.
- Do not declare recovery complete from `/health` alone.

## 7) Paper-only boundary (operational meaning)

- No real-money order execution claims.
- No production-capital readiness claims.
- Public messaging remains paper-only.
- Any capital/live-trading claim escalation requires a separate validated lane.
