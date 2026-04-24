# Fly Runtime Troubleshooting (Operator Quick Guide)

## A) Startup contract quick-check

Expected deployment contract:
- entrypoint = `python -m projects.polymarket.polyquantbot.scripts.run_api`
- startup/alive check = `GET /health`
- readiness check = `GET /ready`
- single polling machine (`min_machines_running=1`, `max_machines_running=1`)

If observed behavior differs, treat as deployment contract drift.

## B) Machine restart loops

Symptoms:
- App repeatedly starts/stops.
- Health checks flap or fail.

Checks:
1. `fly status -a crusaderbot` for machine churn.
2. `fly logs -a crusaderbot` for startup exceptions/crash loops.
3. Confirm required env exists before repeated restarts.

Actions:
- Use **restart** for transient runtime hangs.
- Use **rollback** if issue began after a known bad release.
- Use **redeploy** when code/config/image drift is suspected.

## C) Wrong startup path

Symptoms:
- Runtime boots but API/Telegram services never become healthy.

Checks:
1. Inspect deploy logs for launch command.
2. Confirm runtime module path matches deployment contract.
3. Validate `/health` and `/ready` after boot.

## D) Health/ready mismatch

Pattern:
- `/health` is OK but `/ready` is degraded.

Interpretation:
- Process is alive, but runtime dependencies are not operationally ready.

First checks:
1. Telegram startup logs.
2. Runtime env expectations (without exposing secrets).
3. Recent deploy/restart timeline.

## E) Restart vs rollback vs redeploy

- **Restart**: same release, fast recovery attempt.
- **Rollback**: return to last known-good release.
- **Redeploy**: new release cycle for code/config/image updates.

Rollback commands:
1. `fly releases -a crusaderbot`
2. `fly releases rollback <RELEASE_ID> -a crusaderbot`

## F) Post-action smoke tests

Run after restart, rollback, or redeploy:
1. `curl -fsS https://crusaderbot.fly.dev/health`
2. `curl -fsS https://crusaderbot.fly.dev/ready`
3. `fly logs -a crusaderbot | grep -E "crusaderbot_telegram_runtime_started|crusaderbot_runtime_transition"`
4. Verify Telegram `/start`, `/help`, `/status` responses.

Only declare recovery complete when all four checks pass.
