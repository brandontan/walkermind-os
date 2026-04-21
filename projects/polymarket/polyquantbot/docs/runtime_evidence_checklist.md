# Runtime Evidence Capture Checklist (Reusable)

Use this checklist whenever runtime verification is required.

## Endpoint evidence

- [ ] Root endpoint (`/`) reachable capture
- [ ] `/health` response capture
- [ ] `/ready` response capture

## Telegram evidence

- [ ] `/start` response capture
- [ ] `/help` response capture
- [ ] `/status` response capture

## Runtime/log evidence

- [ ] Fly logs screenshot covering startup + command handling window
- [ ] Sentry screenshot (if applicable) showing event-state for verification window

## Evidence hygiene

- [ ] Timestamps visible in captures
- [ ] Secrets/tokens redacted
- [ ] Notes include deploy/restart context (restart vs redeploy)
