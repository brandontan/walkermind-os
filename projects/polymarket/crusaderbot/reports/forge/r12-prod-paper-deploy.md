# WARP•FORGE Report — R12 Production Paper Deploy

Branch: `WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY`
Issue: #900
Validation Tier: **MAJOR**
Claim Level: **NARROW INTEGRATION** (downgraded from issue-stated FULL
RUNTIME INTEGRATION — see §5 below for the rationale)
Validation Target: production-deploy safety + monitoring code path
(Sentry SDK init, `/health` demo-readiness contract, `/admin/sentry-test`
verification endpoint, fly.toml region alignment, `/kill` and `/resume`
operator aliases) plus three runbook documents covering operator-executed
prod verification.
Not in Scope: live execution of the prod verification checklist itself
(Sentry test event landing in the real production project, Fly.io alert
simulation, Telegram kill-switch end-to-end against `crusaderbot.fly.dev`,
rollback dry-run); activation-guard activation (all remain NOT SET); CLOB
phase 4; demo-data seeding (Lane 1C, separate PR); Telegram polish
(Lane 2C, separate PR); `lib/` cleanup (deferred lane).
Suggested Next Step: WARP🔹CMD or operator executes the verification
checklist per the three new runbooks, then WARP•SENTINEL audit (MAJOR),
then WARP🔹CMD merge decision.

---

## 1. What was built

Five additions hardening `crusaderbot.fly.dev` for the investor demo and
paper-mode production use, plus three runbook documents capturing the
operator-executed prod verification steps.

### (1) Sentry SDK wiring (DSN-gated, no-op when unset)

`monitoring/sentry.py` exposes `init_sentry()`, `capture_test_event()`,
and `is_initialised()`. Init is gated on `SENTRY_DSN` being set as a Fly
secret — when unset (local / CI), every helper is a quiet no-op so the
test suite and dev workstations never ship synthetic events to the
production project. The init helper catches every exception so a
misconfigured DSN cannot block FastAPI startup. Production tags every
event with `environment=APP_ENV` and `release=APP_VERSION` (git short
SHA), with `traces_sample_rate=0.0` by default to keep the project
errors-only.

`main.py` lifespan calls `init_sentry()` first, before env validation,
so any subsequent boot exception lands in Sentry under the right
release.

### (2) `POST /admin/sentry-test` verification endpoint

`api/admin.py` adds a bearer-protected admin endpoint that fires a
synthetic Sentry message via the SDK. Returns
`{"ok": true, "event_id": "<id>"}` when capture succeeds, or
`{"ok": false, "reason": "sentry_not_initialised", "hint": ...}` (still
HTTP 200) when the SDK was not initialised — the runbook can then
distinguish "DSN not set" from "endpoint forbidden". Same
`ADMIN_API_TOKEN` gate as the other `/admin` routes.

### (3) `/health` evolution to demo-readiness contract

`api/health.py` extends the response payload with the brief-required
keys while preserving the R12b deep-dependency keys:

```json
{
  "status": "ok",
  "uptime_seconds": 1234,
  "version": "abc1234",
  "mode": "paper",
  "timestamp": "2026-05-08T12:34:56.789Z",
  "service": "CrusaderBot",
  "checks": { "database": "ok", "telegram": "ok",
              "alchemy_rpc": "ok", "alchemy_ws": "ok" },
  "ready": true
}
```

`mode` reads the three operator activation guards (`ENABLE_LIVE_TRADING`,
`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`) and returns
`"paper"` whenever any of them is unset — i.e. live mode requires ALL
three explicitly True. This mirrors the contract the risk gate already
enforces.

`uptime_seconds` is captured at module import via `time.monotonic()` so
restarts reset the counter cleanly. `version` falls back to the literal
`"unknown"` when `APP_VERSION` is unset rather than emitting `null`.
`timestamp` is an ISO-8601 UTC string with a `Z` suffix.

### (4) `fly.toml` region alignment (`sin` → `iad`)

`fly.toml` `primary_region` updated from `sin` (Singapore) to `iad`
(Ashburn) to match the actual deployed machine region — config-only
alignment as ratified by WARP🔹CMD on 2026-05-08. No machine move and no
redeploy needed; the next routine deploy will pick up the config.

`[[services.http_checks]]` was already wired to `/health` from R12b and
is unchanged. The `[[services]]` (TCP) block is retained rather than
migrated to `[http_service]`: `[http_service]` defaults `auto_stop_machines=true`
which is incompatible with a 24/7 trading bot, and the existing
`[[services.http_checks]]` already provides Fly's HTTP-layer health
checks plus auto-restart on failure.

### (5) `/kill` and `/resume` Telegram aliases

`bot/handlers/admin.kill_command` and `resume_command` are thin wrappers
around the existing `_apply_killswitch_action(...)` path used by
`/killswitch pause` / `/killswitch resume`. Same audit row, same
broadcast fan-out, same operator allowlist gate — the aliases simply
make the demo-flow command surface investor-friendly. Registered in
`bot/dispatcher.py`.

### (6) Three runbook documents

- `docs/runbooks/alerts.md` — Telegram + Fly.io + Sentry alert surfaces,
  cooldown semantics, expected message bodies, verification commands
  with operator-fillable timing logs.
- `docs/runbooks/kill-switch-procedure.md` — pre-flight, demo / drill
  procedure (`/kill` → verify → `/resume`), lock-variant guidance,
  failure modes table, operator-fillable timing logs (target
  `< 3 seconds` ack on `/kill`).
- `docs/runbooks/rollback-procedure.md` — when to roll back vs.
  kill-switch, three rollback paths in increasing blast radius (image
  re-deploy / git rebuild / hot-fix), DB migration rollback caveats
  (forward-only migrations), dry-run procedure that re-deploys the
  CURRENT image so the mechanism is exercised without changing live
  state, post-rollback checklist.

---

## 2. Current system architecture

```
                  ┌────────────────────────────────────────────────┐
                  │  FastAPI (main.py)                             │
                  │   ├── lifespan ── init_sentry() ── (no-op when │
                  │   │                                 DSN unset) │
                  │   │            ── validate_required_env()      │
                  │   │            ── monitoring.alerts.startup    │
                  │   │            ── run_health_checks() at boot  │
                  │   │                                            │
                  │   ├── GET /health                              │
                  │   │     └── monitoring.health.run_health_checks│
                  │   │     └── + uptime_seconds / version / mode  │
                  │   │           / timestamp (route-level)        │
                  │   │     └── monitoring.alerts.schedule_health  │
                  │   │                                            │
                  │   ├── GET /admin/status (bearer)               │
                  │   ├── GET /admin/live-gate (bearer)            │
                  │   ├── POST /admin/kill (bearer)                │
                  │   ├── POST /admin/force-redeem (bearer)        │
                  │   └── POST /admin/sentry-test (bearer)         │
                  │         └── monitoring.sentry.capture_test_event│
                  │                                                │
                  │  Telegram dispatcher                           │
                  │   ├── /killswitch <pause|resume|lock>          │
                  │   ├── /kill   ── alias → pause                 │
                  │   ├── /resume ── alias → resume                │
                  │   └── /ops_dashboard, /jobs, /auditlog, ...    │
                  └────────────────────────────────────────────────┘
                                       │
                                       ▼
                          ┌─────────────────────────────┐
                          │  monitoring.alerts          │
                          │   ├── record_health_result  │
                          │   │     (2x threshold)      │
                          │   ├── alert_startup         │
                          │   ├── alert_missing_env     │
                          │   ├── alert_dependency_     │
                          │   │     unreachable         │
                          │   └── 5-min cooldown,       │
                          │       not armed on send fail│
                          └─────────────────────────────┘
                                       │
                                       ▼
                              Telegram OPERATOR_CHAT_ID
                              + Sentry production project
                              + Fly machine HTTP health probes
```

Surgical edits, not rewrites. The R12b deep-dep layer
(`monitoring/health.py`, `monitoring/alerts.py`,
`monitoring/logging.py`) is unchanged. The `/health` route now layers
the demo-readiness fields on top of the existing payload, and
`/admin/sentry-test` reuses the existing bearer gate.

---

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/monitoring/sentry.py`
- `projects/polymarket/crusaderbot/docs/runbooks/alerts.md`
- `projects/polymarket/crusaderbot/docs/runbooks/kill-switch-procedure.md`
- `projects/polymarket/crusaderbot/docs/runbooks/rollback-procedure.md`
- `projects/polymarket/crusaderbot/reports/forge/r12-prod-paper-deploy.md`

Modified:
- `projects/polymarket/crusaderbot/config.py` — added `SENTRY_DSN`,
  `SENTRY_TRACES_SAMPLE_RATE`, `APP_VERSION` settings (all optional /
  defaulted, no required-env contract change).
- `projects/polymarket/crusaderbot/main.py` — imported
  `monitoring.sentry`, called `init_sentry()` first in the lifespan
  hook so any subsequent boot exception lands in Sentry under the right
  release.
- `projects/polymarket/crusaderbot/api/health.py` — added
  `_uptime_seconds` / `_resolve_mode` / `_resolve_version` / `_now_iso`
  helpers; route now returns the brief-required fields alongside the
  R12b deep-deps payload.
- `projects/polymarket/crusaderbot/api/admin.py` — imported
  `monitoring.sentry`; added `POST /admin/sentry-test` (bearer-gated).
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — added
  `kill_command` and `resume_command` aliases that delegate to the
  shared `_apply_killswitch_action` path.
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registered the
  `/kill` and `/resume` command handlers.
- `projects/polymarket/crusaderbot/fly.toml` — `primary_region`
  `sin` → `iad`.
- `projects/polymarket/crusaderbot/pyproject.toml` — added
  `sentry-sdk[fastapi]>=2.0` dependency.
- `projects/polymarket/crusaderbot/tests/test_health.py` — updated
  `test_health_response_shape_keys_are_stable` comment / contract;
  added 7 new tests covering /health route demo-readiness fields,
  mode resolution across all guard combinations, version fallback,
  /admin/sentry-test admin gate (token unset, wrong token, missing
  token), DSN-unset reason path, success path with mocked SDK, and
  the `init_sentry` no-op contract.

---

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/` — **473 passed**, 1
  warning. Up from 464 before this lane (added 9 tests across the
  /health route + Sentry endpoint surface; 1 existing test had its
  contract comment updated only).
- `python -m py_compile` clean for every file touched.
- `monitoring.sentry.init_sentry()` is idempotent (re-entrant safe) and
  no-ops with one INFO log line when `SENTRY_DSN` is unset.
- `monitoring.sentry.capture_test_event(msg)` returns `None` when the
  SDK is not initialised so the admin endpoint can distinguish from a
  true SDK error.
- `/health` JSON shape verified by tests:
  `{status, uptime_seconds, version, mode, timestamp, service, checks, ready}`
  — every key present, `mode` resolves to `"paper"` whenever ANY of
  the three operator guards is unset, `version` falls back to
  `"unknown"`, `timestamp` is an ISO-8601 UTC string with `Z` suffix.
- `/admin/sentry-test` admin gate returns 503 when `ADMIN_API_TOKEN` is
  unset, 403 with no/wrong bearer, and 200 with the documented JSON
  shapes for both DSN-unset and mocked-success paths.
- `/kill` and `/resume` Telegram handlers route through the same
  `_apply_killswitch_action(...)` path as `/killswitch pause` / `resume`,
  so audit + broadcast + DB writes are byte-identical to the canonical
  command.

---

## 5. Known issues

- **Claim Level downgraded from FULL RUNTIME INTEGRATION → NARROW
  INTEGRATION.** The issue brief lists Done-Criteria items that require
  live execution against `crusaderbot.fly.dev` (Sentry test event
  captured in the production project, Fly.io health alert fires on a
  simulated failure, kill-switch end-to-end < 3 seconds against prod,
  operator dashboard reachable from a real browser, rollback dry-run
  successful). These cannot be honestly executed from the WARP•FORGE
  sandbox — there is no Fly.io / Sentry / Telegram credential available
  to this lane. The runbooks (§1.6 above) capture each step with the
  exact operator command, expected output, and operator-fillable
  timing logs, so WARP🔹CMD or the operator can run the verification
  externally and attach the observed timings. `state/PROJECT_STATE.md`
  is updated to flag this gap explicitly so SENTINEL knows the prod
  artifacts are still pending.
- `ENABLE_LIVE_TRADING: bool = True` is the **code default** in
  `config.py:88`, but `fly.toml` sets `ENABLE_LIVE_TRADING = "false"`
  in the `[env]` block, which takes precedence in production. The
  `_resolve_mode()` helper still returns `"paper"` regardless because
  it requires ALL THREE guards open (and `EXECUTION_PATH_VALIDATED` /
  `CAPITAL_MODE_CONFIRMED` both default `False` in code AND are
  `"false"` in `fly.toml`). Flagged here for SENTINEL — the prod
  posture is correct, but the code default disagrees with the
  intent of "all guards default OFF".
- `check_alchemy_ws()` remains a TCP-level reachability probe, not a
  full WS handshake — pre-existing known issue from R12b. Out of scope
  for this lane; tracked in `state/PROJECT_STATE.md` `[KNOWN ISSUES]`.
- The brief uses `docs/runbooks/` (singular) while issue #900 body uses
  `docs/runbooks/` (plural). The brief is the more recent / detailed
  spec source and was followed. A symlink or rename can be added in a
  trivial follow-up if the plural form is preferred.
- The brief specifies that `/kill` ack should be `< 3 seconds`. The
  Telegram polling architecture caps response latency by
  `MARKET_SCAN_INTERVAL` only on the trading hot path; command handlers
  are dispatched directly off `python-telegram-bot`'s polling loop, so
  ack latency is dominated by the operator chat round-trip
  (typically << 1 second on a healthy machine). Operator must still
  confirm this on prod and log it in the runbook.
- `DEPLOY.md` (repo) was not updated in this lane — out of scope; any
  doc drift between `DEPLOY.md` and the new runbooks should be addressed
  in a follow-up MINOR docs lane.

---

## 5b. Deferred Done-Criteria (operator-executed, NOT CLAIMED CLOSED)

The following Done-Criteria from issue #900 require live infrastructure
access (Fly.io credentials, Sentry production project, real Telegram
bot session, prod database) and are **explicitly deferred** to the
operator. They are NOT closed by this PR and remain open against
issue #900 until the operator attaches the listed artefacts.

| # | Done criterion | Deferred to | Artefact required to close |
| --- | --- | --- | --- |
| 1 | `/health` returns 200 with correct JSON shape **in production** | Operator | `curl -fsS https://crusaderbot.fly.dev/health` output pasted into the PR / issue. Code path verified by 9 unit tests in this PR. |
| 2 | Sentry test event captured in **production project** | Operator | Sentry event id from `POST /admin/sentry-test` per `docs/runbooks/alerts.md` §4.2; screenshot of the event in the Sentry UI. |
| 3 | Health alert fires on simulated failure | Operator | Cold-start Telegram alert observed Δt + screenshot of `OPERATOR_CHAT_ID` chat per `docs/runbooks/alerts.md` §3.2. |
| 4 | `/kill` ack < 3 seconds | Operator | Δt observed in the operator log section of `docs/runbooks/kill-switch-procedure.md` §3.2. |
| 5 | `/resume` reopens the gate | Operator | Δt observed in `docs/runbooks/kill-switch-procedure.md` §3.4. |
| 6 | Operator dashboard reachable | Operator | Screenshot of `/ops_dashboard` rendered in Telegram against prod. |
| 7 | Rollback dry-run successful | Operator | Δt + outcome line recorded in `docs/runbooks/rollback-procedure.md` §5.2. |

This split is the substantive justification for the **NARROW INTEGRATION**
Claim Level: every code path is wired and tested in-PR; every prod
verification is documented as an operator step with operator-fillable
fields in the runbook; nothing in this PR claims a runtime check that
was not actually executed.

`state/PROJECT_STATE.md` `[KNOWN ISSUES]` carries the same deferral note
so post-merge state truth aligns with the report.

---

## 6. What is next

- **Operator / WARP🔹CMD executes the verification checklist** per the
  three new runbooks against `crusaderbot.fly.dev`. Capture the timing
  fields (`Δt = ___ seconds`) and confirm:
  - `/health` returns 200 with the seven documented keys.
  - `/admin/sentry-test` event lands in the production Sentry project.
  - Cold-start Telegram alert fires on a forced machine restart.
  - `/kill` ack < 3 seconds, `/resume` reopens the gate cleanly.
  - Rollback dry-run produces a new release pointing at the same image
    and `/health` returns green within 30 seconds.
- **WARP•SENTINEL audit (MAJOR).** This lane is wired but the prod
  verification artefacts are operator-supplied — SENTINEL should
  validate that the code path matches the runbook commands, not that
  the prod runtime ran them.
- **WARP🔹CMD merge decision** post-SENTINEL.
- After merge: `state/PROJECT_STATE.md` reflects R12 final-deployment
  Lane 1B closure pending operator-executed prod verification.
- **CHECKPOINT 1 — HARD PAUSE** per the batch brief: do not advance to
  Lane 1C (demo data seeding) or Lane 2C (Telegram polish) until
  WARP🔹CMD signals "Lane 1B merged, proceed Lane 1C".
- Follow-up MINOR lane (post-demo): align the `ENABLE_LIVE_TRADING`
  code default to `False` to match fly.toml intent.
- Follow-up MINOR lane (post-demo): full WS handshake check in
  `check_alchemy_ws` (pre-existing carry-over).
