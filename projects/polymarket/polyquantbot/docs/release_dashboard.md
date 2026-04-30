# CrusaderBot — Release Dashboard

Date: 2026-05-01 Asia/Jakarta  
Lane: `WARP/p9-monitoring-admin-surfaces`  
Scope: Priority 9 Lane 3 — release dashboard / admin visibility  
Release posture: public paper-beta path, no live-capital claim

---

## 1. Executive Status

| Area | Status | Notes |
|---|---|---|
| Priority 8 build | Complete | Real CLOB path + capital-mode-confirm build landed, but activation gates remain off |
| Priority 9 Lane 4 | Complete | Repo hygiene final merged via PR #822 |
| Priority 9 Lane 1+2 | Complete | Public docs + ops handoff landed via PR #825, PR #826, PR #827 |
| Priority 9 Lane 3 | In progress on branch | Monitoring/admin surfaces and operator release dashboard |
| Priority 9 Lane 5 | Gated | Final acceptance waits for Lanes 1–4 plus Priority 8 activation decision |
| Live trading | Not authorized | `ENABLE_LIVE_TRADING` remains NOT SET |
| Production capital | Not authorized | `EXECUTION_PATH_VALIDATED` and `CAPITAL_MODE_CONFIRMED` remain NOT SET |

---

## 2. Activation Guard Dashboard

| Guard | Required for | Current posture | Release interpretation |
|---|---|---|---|
| `EXECUTION_PATH_VALIDATED` | Real execution path activation | NOT SET | Live execution path not authorized |
| `CAPITAL_MODE_CONFIRMED` | Capital-mode enablement | NOT SET | Capital mode not authorized |
| Capital DB receipt | Second-layer capital confirmation | Not active unless operator ceremony succeeds | Capital mode incomplete |
| `ENABLE_LIVE_TRADING` | Live trading | NOT SET | Live trading disabled |

Paper-beta public copy must continue to say paper-only / simulated execution unless these gates are intentionally changed and recorded.

---

## 3. Public Paper-Beta Release Readiness

| Requirement | Status | Evidence / path |
|---|---|---|
| Product docs | Complete | `docs/launch_summary.md`, `docs/onboarding.md`, `docs/support.md` |
| Ops handoff | Complete | `docs/ops/deployment_guide.md`, `docs/ops/secrets_env_guide.md`, `docs/ops/runbook_quick_ref.md` |
| Monitoring/admin index | In progress on branch | `docs/ops/monitoring_admin_index.md` |
| Operator checklist | In progress on branch | `docs/ops/operator_checklist.md` |
| Release dashboard | In progress on branch | `docs/release_dashboard.md` |
| Runtime smoke evidence | Required before announcement | `/health`, `/ready`, `/beta/status`, Telegram `/status` |
| Capital guard evidence | Required before announcement | `/beta/capital_status`, Telegram `/capital_status` |
| Known issues visible | Complete / keep current | `docs/support.md`, `state/PROJECT_STATE.md` |

---

## 4. Required Smoke Before Announcement

| Step | Surface | Pass condition |
|---:|---|---|
| 1 | `/health` | Process alive |
| 2 | `/ready` | Readiness result truthful |
| 3 | `/beta/status` | Paper-beta status and limitation copy truthful |
| 4 | `/beta/capital_status` | Gates shown and no hidden capital readiness claim |
| 5 | Telegram `/status` | Operator status reply non-empty |
| 6 | Telegram `/capital_status` | Guard truth matches API |
| 7 | Operator token test | Protected route rejects missing token |
| 8 | Support path | Known issues/support docs are linked and current |

---

## 5. Release Blockers

Any of these blocks public-paper-beta announcement:

- `/ready` returns false without documented reason.
- `/beta/status` claims live trading or capital readiness.
- `/beta/capital_status` contradicts env/DB receipt truth.
- Operator-only routes are accessible without a token.
- Telegram `/status` or `/capital_status` silently fails.
- Support docs omit known critical/deferred issues.
- Docs or public copy imply production-capital readiness.

Any of these blocks live/capital activation:

- `EXECUTION_PATH_VALIDATED` not set.
- `CAPITAL_MODE_CONFIRMED` not set.
- Operator `/capital_mode_confirm` two-step DB receipt missing.
- `ENABLE_LIVE_TRADING` not set.
- Mr. Walker has not authorized activation.

---

## 6. Decision Matrix

| Desired action | Required decision |
|---|---|
| Public paper-beta announcement | WARP🔹CMD final acceptance after Lane 3 + Lane 5 |
| Enable execution-path validation | Mr. Walker + WARP🔹CMD env-gate decision |
| Enable capital mode | Env gate + operator DB receipt ceremony |
| Enable live trading | Explicit separate live-trading authorization |
| Roll back release | Operator/COMMANDER incident decision |

---

## 7. Current Recommendation

Proceed with Priority 9 Lane 3 review and merge, then continue to Lane 5 final acceptance.

Do not enable live trading or production capital during this lane.
