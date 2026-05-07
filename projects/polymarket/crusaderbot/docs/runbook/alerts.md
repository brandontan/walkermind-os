# Alerts Runbook — CrusaderBot

**Owner:** Operator (Bayue Walker)
**Audience:** WARP🔹CMD operator on call.
**Last reviewed:** 2026-05-08 Asia/Jakarta — R12 production-paper deploy.

This runbook covers every alert surface CrusaderBot ships with: Telegram
operator pages, Fly.io machine alerts, and Sentry. Use it during an active
incident, during a scheduled drill, or when verifying production wiring
after a deploy.

---

## 1. Alert surfaces (at a glance)

| Surface | Source | Channel | Trigger |
| --- | --- | --- | --- |
| Operator page | `monitoring.alerts` | Telegram → `OPERATOR_CHAT_ID` | 2 consecutive `/health` failures, missing required env, dependency unreachable at boot, machine cold start |
| Fly.io machine | Fly platform | Fly dashboard + email | `[[services.http_checks]]` failure → automatic restart + alert |
| Sentry | `monitoring.sentry` | Sentry web UI / configured integrations | Any uncaught exception captured by the SDK once `SENTRY_DSN` is set |

The Telegram operator page is the **primary** surface during an incident.
Fly.io and Sentry are secondary — use them for triage detail after the
operator has already been paged.

---

## 2. Telegram operator alerts

### 2.1 Wire-up summary

- Bot token: `TELEGRAM_BOT_TOKEN` (Fly secret).
- Operator chat id: `OPERATOR_CHAT_ID` (Fly secret).
- Dispatcher: `projects/polymarket/crusaderbot/monitoring/alerts.py`.
- Health record path: `monitoring.alerts.record_health_result(result)`,
  scheduled fire-and-forget from the `/health` route.
- Cooldown: 5 minutes per `(alert_type, key)` tuple. The cooldown is **not
  armed** when delivery fails (returns False from `notifications.send`),
  so a permanent outage will keep retrying instead of silently muting.

### 2.2 Triggers and expected message bodies

| Trigger | Cooldown key | Body shape |
| --- | --- | --- |
| 2 consecutive `/health` failures (per check) | `("health_degraded", check_name)` | `🔻 Health degraded: <check_name> error: <reason>` |
| Recovery | resets per-check counter; no message | — |
| Missing required env at boot | `("missing_env", "<sorted-keys>")` | `🚨 Required env missing: KEY1, KEY2, ...` |
| Boot dependency unreachable | `("startup_dep_fail", "<dep_name>")` | `🟠 Boot probe failed: <dep_name> error: <reason>` |
| Machine cold start | `("startup", "machine_restart")` | `🔄 CrusaderBot restarted on Fly.io machine ...` |

### 2.3 Verification — Telegram alert delivery

Run from any operator workstation with `flyctl` available:

```bash
# 1. Confirm secrets are present (values never printed):
flyctl secrets list -a crusaderbot | grep -E '(TELEGRAM_BOT_TOKEN|OPERATOR_CHAT_ID)'

# 2. Confirm /health currently returns 200 ok (baseline):
curl -fsS https://crusaderbot.fly.dev/health | jq '.status, .mode'
# expected: "ok", "paper"

# 3. Trigger a synthetic /health failure (operator-only). The simplest path
#    is to flip the kill switch, which forces the alert dispatcher counter
#    on the next two health probes if you simulate a dependency outage.
#    For a non-destructive test, just observe the cold-start alert by
#    triggering a redeploy:
flyctl deploy -a crusaderbot --strategy immediate
# Watch the operator chat for the "🔄 CrusaderBot restarted" message.
# Expected delivery latency: < 30 seconds after machine boot.
```

**Operator log timing:** record below after each verification.

```
[YYYY-MM-DD HH:MM Asia/Jakarta] cold-start alert observed Δt = ___ seconds.
[YYYY-MM-DD HH:MM Asia/Jakarta] degraded-health alert observed Δt = ___ seconds.
```

---

## 3. Fly.io health alerts

### 3.1 Configuration in `fly.toml`

```
[[services.http_checks]]
  interval     = "10s"
  timeout      = "5s"
  grace_period = "10s"
  method       = "GET"
  path         = "/health"
  protocol     = "http"
```

Three consecutive failures (≥ 30 seconds of the endpoint not returning 200)
cause Fly to restart the machine. Restarts emit a cold-start Telegram alert
via the lifespan hook in `main.py`.

### 3.2 Tighter Fly-side alerting (optional, operator action)

Fly does not natively page operators on machine failure beyond the platform
restart loop. The two paths supported today are:

- **Built-in:** Telegram cold-start alert on every machine boot — fires on
  every Fly-induced restart automatically, no extra wiring needed.
- **External (recommended):** subscribe an operator email to Fly's billing
  / status notifications via `flyctl alerts` (Fly platform feature) so a
  prolonged restart loop also pages outside Telegram.

To verify the built-in path:

```bash
# 1. Observe current machine list:
flyctl machines list -a crusaderbot

# 2. Force-stop the machine (Fly will restart it):
flyctl machine stop <machine-id> -a crusaderbot
flyctl machine start <machine-id> -a crusaderbot

# 3. Watch operator Telegram for cold-start alert.
```

**Operator log timing:** record below after the verification.

```
[YYYY-MM-DD HH:MM Asia/Jakarta] machine restart → cold-start alert Δt = ___ seconds.
```

---

## 4. Sentry

### 4.1 Wire-up summary

- DSN: `SENTRY_DSN` (Fly secret). Init is a no-op when unset.
- Environment tag: derived from `APP_ENV` (`production` in Fly).
- Release tag: `APP_VERSION` (git short SHA at deploy time).
- Traces sample rate: `SENTRY_TRACES_SAMPLE_RATE` (default `0.0` —
  errors-only).
- Integration: FastAPI + Starlette via `sentry_sdk.integrations`.
- Init point: lifespan hook in `main.py`, before any other boot work.

### 4.2 Verification — production test event

Run from any operator workstation with the admin bearer token in hand:

```bash
# Bearer token = ADMIN_API_TOKEN (Fly secret). Never paste it into chat.
TOKEN=$(flyctl secrets list -a crusaderbot --json | jq -r '.[]|select(.Name=="ADMIN_API_TOKEN")|.Digest')
# (The above prints the digest, not the value. Use your stored copy.)

curl -fsS -X POST https://crusaderbot.fly.dev/admin/sentry-test \
  -H "Authorization: Bearer <ADMIN_API_TOKEN>" | jq
```

Expected JSON when `SENTRY_DSN` is set and the SDK initialised:

```json
{ "ok": true, "event_id": "<32-hex-id>" }
```

Expected JSON when `SENTRY_DSN` is NOT set or init failed:

```json
{ "ok": false, "reason": "sentry_not_initialised",
  "hint": "set SENTRY_DSN as a Fly.io secret and redeploy" }
```

After firing the event, open the Sentry production project and confirm the
event appears under the configured release with environment `production`.

**Operator log:**

```
[YYYY-MM-DD HH:MM Asia/Jakarta] /admin/sentry-test event_id = ____________
[YYYY-MM-DD HH:MM Asia/Jakarta] event visible in Sentry UI, release = ____, env = ____
```

---

## 5. Escalation order

1. Telegram operator page — primary signal.
2. Open the Sentry project — recent events, find the matching release.
3. `flyctl logs -a crusaderbot` — search for the `health check failed`
   structured log line near the alert timestamp.
4. `flyctl status -a crusaderbot` — machine state, last deploy, last
   restart.
5. If unresolved within 10 minutes, follow the kill-switch procedure
   (`kill-switch-procedure.md`) to halt new trades while diagnosing.
6. If a recent deploy correlates, follow the rollback procedure
   (`rollback-procedure.md`).

---

## 6. Known gaps and follow-ups

- `check_alchemy_ws` is a TCP-level reachability probe rather than a
  full WebSocket handshake. DNS / SSL / firewall outages are surfaced;
  application-layer auth failures on the WS endpoint are not. Tracked as
  a deferred follow-up in `state/PROJECT_STATE.md`.
- Per-user health alert routing (paging the strategy owner instead of the
  global operator) is out of scope for R12. All alerts page
  `OPERATOR_CHAT_ID`.
