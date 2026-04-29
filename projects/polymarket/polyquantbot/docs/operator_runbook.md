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

## 8) Capital mode incident response (P8-D)

Capital mode uses a 5-gate guard contract. All five must be `true` for LIVE mode to activate.
In PAPER mode the gate contract is not enforced — only risk bounds apply.

### 8.1 Alert events and severity

| Log event | Severity | Meaning |
|---|---|---|
| `capital_mode_guard_blocked` | CRITICAL | LIVE mode attempted with one or more gates off. Check env vars. |
| `capital_daily_loss_limit_tripped` | CRITICAL | Day-scoped PnL hit -$2,000 hard stop. Trading halted for the day. |
| `capital_daily_loss_approaching_limit` | WARNING | Day-scoped PnL reached 75% of daily limit (-$1,500). Monitor closely. |
| `operator_admin_intervention_audit` | INFO | Audit record for every `apply_admin_intervention()` call. |

### 8.2 Daily loss limit trip procedure

1. Gate trips automatically — no new signals accepted until midnight Jakarta (UTC+7).
2. Check log: `fly logs -a crusaderbot | grep capital_daily_loss_limit_tripped`
3. Review today's PnL via Telegram: `/capital_status` (operator chat only)
4. Do NOT manually reset `daily_open_realized_pnl` — the reset happens automatically at midnight Jakarta.
5. If override required: stop the worker via `/kill`, investigate, restart only after root cause is resolved.

### 8.3 Capital gate guard trip procedure

Symptom: `capital_mode_guard_blocked` in logs; worker may raise `CapitalModeGuardError`.

1. Run `/capital_status` in operator Telegram to see which gates are off.
2. Check `ENABLE_LIVE_TRADING`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`,
   `EXECUTION_PATH_VALIDATED`, `SECURITY_HARDENING_VALIDATED` env vars in Fly secrets.
3. A gate should only be set to `true` after the corresponding SENTINEL MAJOR validation is approved.
4. If gate was accidentally set: `fly secrets set <KEY>=false -a crusaderbot && fly deploy --strategy immediate`.

### 8.4 `/capital_status` command reference

Command: `/capital_status` (operator Telegram only — requires OPERATOR_CHAT_ID match)

Returns:
- All 5 gate booleans
- Current trading mode (PAPER / LIVE)
- Daily PnL vs. limit
- Drawdown and exposure vs. limits
- Kill switch state
- Kelly fraction (must be 0.25)

### 8.5 Permission model boundary

- User routes: session-authenticated via `X-Session-Id` / `X-Auth-*` trusted headers.
- Capital/operator routes: `X-Operator-Api-Key` header required.
- Portfolio routes: hardcode `paper_user` scope — per-user binding deferred to Priority 9.
