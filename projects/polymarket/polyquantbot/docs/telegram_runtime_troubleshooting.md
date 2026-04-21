# Telegram Runtime Troubleshooting (Paper-Beta Safe)

## 1) No bot reply

Check sequence:
1. Confirm Fly app is reachable (`/health`, `/ready`).
2. Check logs for Telegram runtime start.
3. Send `/start`, then `/help`, then `/status` in that order.
4. Review logs for inbound update and command handler output.

If no inbound updates appear, check token validity and webhook/polling mode conflicts.

## 2) Polling conflict / HTTP 409

Symptoms:
- Logs show polling conflict / terminated getUpdates session.

Actions:
1. Ensure single active polling machine.
2. Clear conflicting webhook if needed.
3. Restart runtime after conflict removal.
4. Re-test `/start` and `/help`.

## 3) Token rotation / revoke recovery

When token is rotated/revoked:
1. Update token secret in Fly environment.
2. Restart or redeploy runtime so new token is loaded.
3. Watch startup logs for successful Telegram initialization.
4. Run baseline command checks (`/start`, `/help`, `/status`).

Never print token values in logs, docs, or screenshots.

## 4) Webhook conflict checks

If polling is expected:
- Verify no active webhook is hijacking updates.
- Resolve webhook conflict first, then resume polling.

## 5) Baseline command expectations

- `/start`: onboarding + paper-only posture guidance.
- `/help`: public-safe command guidance.
- `/status`: paper runtime status surface without overclaim.

Any command returning empty/incorrect fallback or `/start`-collapsed behavior is a troubleshooting trigger.

## 6) What to inspect in logs

Look for:
- Bot startup/initialization success line.
- Inbound command receipt line.
- Handler dispatch line (`/start`, `/help`, `/status`).
- Reply success/failure line.
- Runtime exceptions and stack traces.

## 7) Public-safe command posture

Keep public-facing guidance restricted to trusted paper-safe command surface.
Do not expose operator-only or not-ready commands in public help text.
