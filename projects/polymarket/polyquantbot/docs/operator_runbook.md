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

## 9) Capital mode activation procedure (P8-E)

The `CAPITAL_MODE_CONFIRMED` gate is now defended in two layers:

1. **Env var** — `CAPITAL_MODE_CONFIRMED=true` set in deployment secrets; read once at process start.
2. **DB receipt** — an unrevoked row in `capital_mode_confirmations`, inserted only via the operator confirmation flow described below.

`LiveExecutionGuard.check_with_receipt()` requires both layers. Either missing ⇒ live execution refused with reason `capital_mode_env_gates_missing` or `capital_mode_no_active_receipt`.

### 9.1 Activation checklist (in order)

Do these steps in order. Each step is gated on the previous succeeding.

1. **Pre-flight upstream** — confirm prior SENTINEL gates have all been set in deployment secrets:
   - `ENABLE_LIVE_TRADING=true`
   - `RISK_CONTROLS_VALIDATED=true`
   - `EXECUTION_PATH_VALIDATED=true`
   - `SECURITY_HARDENING_VALIDATED=true`
2. **Set the env layer** — `fly secrets set CAPITAL_MODE_CONFIRMED=true -a crusaderbot && fly deploy --strategy immediate`.
3. **Confirm gate visibility** — operator Telegram: `/capital_status`. All 5 gates must show ✅. If any show ❌, stop and reconcile env before continuing.
4. **Issue receipt — step 1/2** — operator Telegram: `/capital_mode_confirm` (no argument). Bot replies with a 16-character hex token, the gate snapshot, and a 60-second TTL window.
5. **Commit receipt — step 2/2** — operator Telegram (within 60s): `/capital_mode_confirm <token>`. Bot replies with the persisted `confirmation_id` + `confirmed_at` timestamp. The gate is now fully open.
6. **Verify** — issue any live-execution-bound action (or check `/capital_status` for `capital_mode_allowed: true`). The `live_execution_guard_with_receipt_passed` event must appear in structured logs.

If step 4 or 5 fails with `rejected_missing_gates`, return to step 1 and reconcile the listed env vars. Do not retry the confirm flow until all gates show green.

### 9.2 Rollback / revoke procedure (incident response)

Use this when an incident requires immediately disabling live execution without waiting for an env redeploy.

1. Operator Telegram: `/capital_mode_revoke <reason>`. Single-step (no token) — must be fast.
2. Bot replies with the revoked `confirmation_id`, `revoked_at`, and the reason captured in the audit log.
3. Subsequent `LiveExecutionGuard.check_with_receipt()` calls now refuse with reason `capital_mode_no_active_receipt`. Live execution paths halt deterministically.
4. To re-arm: repeat §9.1 steps 4–6 once root cause is resolved. Env vars remain unchanged — only the DB receipt is revoked.

For full env rollback (if the incident is at the env-gate layer), additionally: `fly secrets set CAPITAL_MODE_CONFIRMED=false -a crusaderbot && fly deploy --strategy immediate`.

### 9.3 Audit trail surfaces

Every confirm/revoke outcome — success, refusal, token mismatch, store unavailable — emits a structured event:

| Log event | Severity | Emitted on |
|---|---|---|
| `capital_mode_confirm_attempt` | INFO / WARNING | every step-1 issuance, step-2 commit, refusal, token mismatch, store-not-ready |
| `capital_mode_revoke_attempt` | INFO / WARNING | every revoke call (success + no-active-row) |
| `live_execution_guard_with_receipt_passed` | INFO | each guard pass with both layers green |
| `live_execution_guard_blocked` | WARNING | each guard refusal — `reason` includes `capital_mode_no_active_receipt` when only the DB layer is missing |

Tail with: `fly logs -a crusaderbot | grep -E "capital_mode_(confirm|revoke)_attempt|live_execution_guard"`.

### 9.4 Boundary reminders

- The two commands `/capital_mode_confirm` and `/capital_mode_revoke` are gated to the operator chat-id match (`_INTERNAL_COMMANDS`). Non-operator users cannot reach the endpoints from Telegram.
- The HTTP routes themselves require `X-Operator-Api-Key`. Direct API access without that header returns 403.
- Pending tokens are held in-process (`_PENDING_CAPITAL_CONFIRMS`). A process restart between step 1 and step 2 invalidates the pending token; operator must re-issue from step 1.
