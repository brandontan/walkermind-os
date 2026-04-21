# Sentry Quick-Check (Operator)

## 1) Environment expectation

- `SENTRY_DSN` should be configured in Fly env/secret storage for event delivery.
- Keep DSN value secret; do not expose raw value in screenshots or chat.

## 2) "First event not seen yet" meaning

- Integration can be present in code while no qualifying error/event has occurred yet.
- "No event yet" is not automatic proof of broken integration.

## 3) Code integration vs deploy-event proof

Treat these as separate checks:
1. **Code integration present**: runtime includes Sentry init/capture path.
2. **Operational event proof**: deployed runtime emitted at least one event visible in Sentry.

If #1 is true and #2 is pending, posture should be: integration landed, event proof pending verification.

## 4) Minimal safe first-check flow

1. Confirm `SENTRY_DSN` is set (without revealing value).
2. Confirm runtime starts cleanly with no Sentry init errors.
3. Inspect Sentry project for recent events during verification window.
4. If no event appears, record as pending operational proof (not assumed broken).
