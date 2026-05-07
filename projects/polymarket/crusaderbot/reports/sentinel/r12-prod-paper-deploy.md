# WARP•SENTINEL Report — R12 Production Paper Deploy

Branch: `WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY`
Issue: #903
PR: #901
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION (FORGE-declared)
Feature: `r12-prod-paper-deploy`
Date: 2026-05-08 16:00 Asia/Jakarta

---

## 1. Environment

| Item | Value |
|---|---|
| Target env | `production` (paper-mode — all activation guards NOT SET) |
| Infra | ENFORCED |
| Risk | ENFORCED |
| Telegram | ENFORCED |
| Project root | `projects/polymarket/crusaderbot` |
| CI result | 473/473 passed (PR body) |
| Python | 3.11+ |

---

## 2. Validation Context

| Item | Value |
|---|---|
| Issue | #903 |
| PR | #901 |
| Branch | `WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY` |
| Branch format | COMPLIANT — `WARP/{FEATURE-NAME}` |
| Tier | MAJOR |
| Claim Level | NARROW INTEGRATION (downgraded from FULL RUNTIME — operator prod verification deferred) |
| Validation target | Sentry SDK init; `/health` demo-readiness contract + activation guard `mode` field; `/admin/sentry-test` bearer endpoint; `/kill` + `/resume` Telegram aliases; `fly.toml` `primary_region` alignment; 3 runbook docs |
| Not in scope | Risk gate internals; pre-existing monitoring stack; activation guard activation; prod runtime verification (deferred to operator per NARROW INTEGRATION claim) |

---

## 3. Phase 0 Checks

| Check | Result | Evidence |
|---|---|---|
| PR exists and is open | PASS | PR #901 state=open, merged=false |
| Branch matches `WARP/{FEATURE-NAME}` | PASS | `WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY` |
| Forge report at correct path | PASS | `projects/polymarket/crusaderbot/reports/forge/r12-prod-paper-deploy.md` present in PR files |
| Forge report has all 6 sections | PASS | §1 What was built, §2 Architecture, §3 Files, §4 Working, §5 Known issues, §6 Next |
| `state/PROJECT_STATE.md` updated with timestamp | PASS | PR diff: `Last Updated: 2026-05-08 14:00 Asia/Jakarta` |
| No `phase*/` folders | PASS | GitHub code search: 0 results for phase-prefixed paths under project root |
| No hardcoded secrets | PASS | `fly.toml` uses Fly secrets; `sentry.py` reads `os.environ` directly; no inline credentials in any changed file |
| No full Kelly (a=1.0) | PASS | No trading logic changes in this PR |
| No silent exception handling | PASS | `monitoring/sentry.py:83` catches `Exception`, logs via `logger.error`, does not re-raise |
| No threading in async context | PASS | No `import threading` in any changed file |

**Phase 0: ALL PASS**

---

## 4. Findings

### Phase 1 — Functional

**F1.1 Sentry init: DSN-gate and boot isolation** — PASS

- `monitoring/sentry.py:50-51` — `if _initialised: return True` — idempotent, safe on cold restart
- `monitoring/sentry.py:55-57` — `if not dsn: logger.info("Sentry disabled"); return False` — quiet no-op when `SENTRY_DSN` unset
- `monitoring/sentry.py:72-85` — `try: sentry_sdk.init(...); _initialised = True; return True` / `except Exception as exc: logger.error("Sentry init failed: %s", exc); return False` — init failure cannot block FastAPI boot
- `main.py` — `monitoring_sentry.init_sentry()` is FIRST call in lifespan, before env validation — all subsequent boot exceptions are captured

**F1.2 /health demo-readiness contract** — PASS

- `api/health.py:_resolve_mode()` — `if s.ENABLE_LIVE_TRADING and s.EXECUTION_PATH_VALIDATED and s.CAPITAL_MODE_CONFIRMED: return "live"; return "paper"` — requires ALL three guards True; any unset → `"paper"`
- Test coverage: `test_health_mode_paper_when_any_guard_off` — 5 guard combinations: (F,F,F), (T,F,F), (T,T,F), (F,T,T) → `"paper"`; (T,T,T) → `"live"`
- Route returns `{status, uptime_seconds, version, mode, timestamp, service, checks, ready}` — 8-key shape verified by `test_health_route_demo_readiness_fields`
- `_uptime_seconds()` — O(1) monotonic diff, no I/O
- `_resolve_version()` — `APP_VERSION → "fly-v{N}" → "unknown"` fallback chain; three dedicated tests covering each fallback leg
- `monitoring_alerts.schedule_health_record(result)` called BEFORE enriched payload returned — alert path preserved, not bypassed

**F1.3 /admin/sentry-test bearer gate** — PASS

- `api/admin.py:20-24` — `_check(token)` uses `secrets.compare_digest(token, expected)` — timing-safe
- New endpoint calls `_check(token)` FIRST before any SDK interaction
- DSN unset path: `{"ok": false, "reason": "sentry_not_initialised", "hint": "set SENTRY_DSN..."}` — runbook-actionable
- `capture_test_event()` returns None path: `{"ok": false, "reason": "capture_returned_none"}`
- Success path: `{"ok": true, "event_id": "<id>"}`
- Test coverage: `test_admin_sentry_test_requires_admin_token` (503 unset / 403 missing / 403 wrong), `test_admin_sentry_test_reports_dsn_unset_when_not_initialised`, `test_admin_sentry_test_returns_event_id_when_initialised`

**F1.4 /kill and /resume Telegram aliases** — PASS

- `bot/handlers/admin.py:kill_command` — `_is_operator(update)` gate → `_apply_killswitch_action("pause", ...)` — no new execution logic
- `bot/handlers/admin.py:resume_command` — `_is_operator(update)` gate → `_apply_killswitch_action("resume", ...)` — no new execution logic
- Same operator gate, same audit row, same broadcast fan-out as canonical `/killswitch pause/resume`
- `bot/dispatcher.py` — `CommandHandler("kill", ...)` and `CommandHandler("resume", ...)` registered

**F1.5 fly.toml region alignment** — PASS

- Diff: `primary_region = "sin" → "iad"` — config-only, no machine count changes
- `[[services]]` TCP block retained (not migrated to `[http_service]`) — correct; avoids `auto_stop_machines=true` which is incompatible with 24/7 operation
- `[[services.http_checks]]` path `/health` — unchanged, wired
- `[env]`: all 5 activation guards remain `"false"`; no secrets present in toml

### Phase 2 — Pipeline

**F2.1 Health alert path preserved** — PASS

- `api/health.py:104` — `monitoring_alerts.schedule_health_record(result)` fired with the underlying health check result before the demo-readiness enrichment is added. Alert dispatcher still receives the raw check result, not the enriched payload.

**F2.2 Sentry init position in lifespan** — PASS

- `main.py` lifespan: `init_sentry()` → `validate_required_env()` → pool init → migrations → bot → scheduler. Boot exceptions after `init_sentry()` are captured under the correct release tag.

### Phase 3 — Failure Modes

**F3.1 Sentry init exception isolation** — PASS

- `monitoring/sentry.py:83-84` — catches `Exception`, logs via `logger.error`, returns False. Never re-raises. FastAPI boot continues.

**F3.2 Malformed `SENTRY_TRACES_SAMPLE_RATE`** — PASS

- `monitoring/sentry.py:41-50` — `except (TypeError, ValueError): logger.warning(...); return 0.0` — operator typo cannot block boot
- `SENTRY_TRACES_SAMPLE_RATE` removed from `Settings` class — malformed value cannot cause `pydantic.ValidationError` on `get_settings()` calls elsewhere in the app
- Tests: `test_settings_does_not_validate_sentry_traces_sample_rate`, `test_init_sentry_traces_sample_rate_malformed_falls_back`

**F3.3 Sentry test event capture failure** — PASS (minor test-coverage gap, P2)

- `monitoring/sentry.py:116-121` — catches `Exception` in `capture_test_event`, logs, returns None. Admin endpoint returns `{"ok": false, "reason": "capture_returned_none"}`.
- Minor: no test exercises the SDK-initialized + `sentry_sdk.capture_message` returns None natively (only mocked). Code handling is correct; gap is test coverage only. Deferred P2.

### Phase 4 — Async Safety

**F4.1 `_initialised` global access** — PASS

- `init_sentry()` called from the lifespan startup hook; completes before FastAPI accepts any requests. No concurrent initialization risk in the production execution model.
- `reset_for_tests()` is test-only; not reachable from any route.

### Phase 5 — Risk Rules

**F5.1 Activation guards not mutated** — PASS

- No `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, or any other activation guard value changed in any Python file in this PR.
- `fly.toml` `[env]`: all 5 activation guards remain `"false"`.

**F5.2 `ENABLE_LIVE_TRADING: bool = True` code default** — P2 ADVISORY

- `config.py:88` (pre-existing, not introduced by this PR) — code default is `True`.
- Mitigated: `EXECUTION_PATH_VALIDATED: bool = False` + `CAPITAL_MODE_CONFIRMED: bool = False` code defaults mean live mode requires ALL THREE guards explicitly True. A default local run cannot reach live mode.
- fly.toml `[env]` sets `ENABLE_LIVE_TRADING = "false"` as defense-in-depth for production.
- Flagged in forge report §5, `state/PROJECT_STATE.md [KNOWN ISSUES]`, and PR #901 notes.
- Classification: **P2 — post-merge MINOR lane** (production safe; semantic misalignment only)

### Phases 6–7 — Latency / Infra

**F6.1 /health route additions** — PASS

- `_uptime_seconds()`, `_resolve_mode()`, `_resolve_version()`, `_now_iso()` — all O(1), no I/O, no DB queries. Health route latency unchanged vs. R12b baseline.

**F7.1 Fly.io infra wiring** — PASS

- `[[services.http_checks]]` wired to `/health` with `interval=10s, timeout=5s, grace_period=10s` — Fly HTTP health check probes the enriched endpoint correctly.

### Phase 8 — Telegram

**F8.1 /kill and /resume broadcast path** — PASS

- Both aliases route through `_apply_killswitch_action` — writes audit row (`kill_switch_pause`/`kill_switch_resume`), emits broadcast fan-out to active subscribers, writes `system_settings.kill_switch_active`. Byte-identical behaviour to canonical `/killswitch pause/resume`.
- Runbook `docs/runbooks/kill-switch-procedure.md` documents expected bot reply bodies, operator log timing targets (`< 3 seconds`), and failure modes table.

---

## 5. Score Breakdown

| Category | Weight | Score | Weighted |
|---|---|---|---|
| Architecture | 20% | 20/20 | 20 |
| Functional | 20% | 20/20 | 20 |
| Failure modes | 20% | 19/20 | 19 |
| Risk | 20% | 18/20 | 18 |
| Infra + Telegram | 10% | 9/10 | 9 |
| Latency | 10% | 9/10 | 9 |
| **Total** | | | **95/100** |

Deduction rationale:
- Failure modes (−1): `capture_test_event` returns-None path not tested with SDK-initialized state (mock only; code handling correct)
- Risk (−2): `ENABLE_LIVE_TRADING: bool = True` code default semantic misalignment — pre-existing P2, production safe via fly.toml override and dual guard
- Infra + Telegram (−1): 7 deferred operator prod verification artefacts not collected — expected under NARROW INTEGRATION claim
- Latency (−1): No prod latency data; O(1) additions verified in code only

---

## 6. Critical Issues

**P0 issues: 0**
**P1 issues: 0**

No blocking issues found.

---

## 7. Status

**APPROVED**

Score ≥ 85. Zero P0 and P1 critical issues. All Phase 0 checks pass. Claim level is NARROW INTEGRATION — operator prod verification explicitly deferred and documented in runbooks; not a deficiency.

---

## 8. PR Gate Result

PR #901 (`WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY`) is **CLEARED FOR MERGE** pending WARP🔹CMD final decision.

WARP•SENTINEL does not merge. WARP🔹CMD decides.

---

## 9. Fix Recommendations

**P2 — deferred, post-merge MINOR lane:**

1. `config.py:88` — `ENABLE_LIVE_TRADING: bool = True` — change to `False` to align with the intent of "all activation guards default OFF". fly.toml override is the production gate until corrected. Recommend branch `WARP/config-guard-default-alignment` (MINOR).

2. `monitoring/sentry.py:capture_test_event` — add a unit test for the path where `_initialised=True` but `sentry_sdk.capture_message` returns `None` natively (not via exception). Code handling is correct; gap is test coverage only.

---

## 10. Out-of-Scope Advisory

- `ENABLE_LIVE_TRADING: bool = True` is a pre-existing issue predating this PR. Noted as P2 above.
- `check_alchemy_ws()` TCP-only probe (pre-existing from R12b) — no change in this PR. Tracked in KNOWN ISSUES.
- `DEPLOY.md` drift vs. new runbooks — out of scope. Flag for a MINOR docs lane post-demo.
- No `phase*/` folders found under project root.
- `services/*` dead code — pre-existing, not touched by this PR.

---

## 11. Deferred Minor Backlog (P2 items)

```
- [P2] ENABLE_LIVE_TRADING code default True in config.py:88 — change to False; WARP/config-guard-default-alignment (MINOR, post-demo)
- [P2] capture_test_event returns-None path — add unit test for SDK-initialized + None return; any passing lane
```
