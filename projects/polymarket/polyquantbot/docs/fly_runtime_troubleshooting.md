# Fly Runtime Troubleshooting (Operator Quick Guide)

## A) Machine restart loops

Symptoms:
- App repeatedly starts/stops.
- Health checks flap or fail.

Checks:
1. `fly status` for machine lifecycle churn.
2. `fly logs` for startup exceptions and crash loops.
3. Confirm required env is present before repeated restarts.

Actions:
- Use **restart** for transient runtime hangs.
- Use **redeploy** when config/image/code drift is suspected.

## B) Wrong startup path

Symptoms:
- Runtime starts but expected API/Telegram services never become healthy.

Checks:
1. Inspect launch command/entrypoint from deploy logs.
2. Confirm app starts intended module/process path.
3. Validate `/health` vs `/ready` output after boot.

## C) Health/ready mismatch

Pattern:
- `/health` returns OK but `/ready` remains degraded.

Interpretation:
- Process is alive, but dependencies/runtime integrations are not fully ready.

First checks:
1. Telegram polling startup logs.
2. Runtime env expectations (without exposing secrets).
3. Recent deploy/restart timeline.

## D) Single-machine polling requirement for Telegram

- Polling mode should run on a single active machine to avoid polling conflicts (e.g., duplicate consumers / 409 conflicts).
- If scaling/restart operations accidentally create overlap, reduce to one active polling runtime and re-check logs.

## E) Restart vs redeploy distinction

- **Restart**: same build/config, quick recovery attempt.
- **Redeploy**: new release cycle (code/config/image), use when startup path/config drift is likely.

## F) What to read first in Fly logs

Prioritize, in order:
1. Process boot line (entrypoint/module confirmation).
2. Runtime init lines (API startup, monitor/runtime guards).
3. Telegram polling/session lines.
4. Exception traces around startup window.
5. Readiness-related warnings/errors.

## G) Rollback and post-deploy smoke contract (Phase 11.1)

Rollback baseline:
1. `fly releases` to identify the previous healthy release.
2. `fly deploy --image <previous-image-ref>` to pin rollback to known-good image when config did not change.
3. Re-run smoke checks immediately after rollback completion.

Post-deploy smoke checks (staging/prod):
1. `curl -fsS https://<app-host>/health` returns HTTP 200.
2. `curl -fsS https://<app-host>/ready` returns HTTP 200 with readiness payload.
3. `fly logs --no-tail` shows startup path `projects.polymarket.polyquantbot.scripts.run_api` and no secret-like value leakage.
4. If Telegram runtime is required, verify a single active machine and no polling conflict errors.
