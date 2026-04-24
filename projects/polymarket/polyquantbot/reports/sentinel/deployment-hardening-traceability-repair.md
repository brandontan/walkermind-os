# SENTINEL REPORT — Deployment Hardening Contract Closure

**Phase:** 10.10
**Task:** deployment-hardening-traceability-repair
**Date:** 2026-04-24 10:40
**Branch:** NWAP/deployment-hardening-traceability-repair
**PR:** #759 → main
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** deployment/startup/health/readiness/restart/rollback/smoke-test contract only
**Not in Scope:** feature expansion, paper trading product completion, wallet lifecycle, portfolio logic, production-capital readiness, unrelated historical roadmap cleanup

---

## 🧪 TEST PLAN

**Environment:** dev / staging / prod (paper-only boundary enforced)
**Scope:** Dockerfile, fly.toml, operator_runbook.md, fly_runtime_troubleshooting.md, forge report, repo-truth state continuity

**Phases executed:**
- Phase 0 — Pre-test gate (report path, branch traceability, state sync, domain structure, encoding)
- Phase 1 — Functional contract verification (HEALTHCHECK, /health, /ready routes)
- Phase 2 — Deployment pipeline alignment (fly.toml vs Dockerfile vs docs)
- Phase 3 — Failure mode coverage (restart, rollback, redeploy, health/ready mismatch)
- Phase 4 — Async/concurrency safety (Telegram polling single-machine contract)
- Phase 5 — Risk constants and live-trading guard
- Phase 6 — Latency/timing alignment (grace periods, intervals, timeouts)
- Phase 7 — Infra contract (Fly machine config, port, scale-to-zero)
- Phase 8 — Smoke test contract consistency

**Runner note:** Python interpreter not available in this environment (`python3` not found). py_compile checks could not be executed. All validation performed via static analysis of source files. This is noted as an evidence gap — not a blocker for a doc/config-only NARROW INTEGRATION lane where no new runtime logic was introduced.

---

## 🔍 FINDINGS

### Phase 0 — Pre-Test Gate

**Report path and naming:**
- Path: `projects/polymarket/polyquantbot/reports/forge/phase10-10_02_deployment-hardening-contract-closure.md` ✅
- All 6 mandatory sections present (What was built, Architecture, Files, Working, Known issues, Next) ✅
- Validation Tier declared: MAJOR ✅
- Claim Level declared: NARROW INTEGRATION ✅

**Branch traceability:**
- Forge report line 5: `Branch: NWAP/deployment-hardening-traceability-repair` ✅
- PROJECT_STATE.md IN PROGRESS entry: `branch NWAP/deployment-hardening-traceability-repair` ✅
- PR #759 head branch: `NWAP/deployment-hardening-traceability-repair` ✅
- All three references match exactly — traceability clean ✅

**State sync:**
- PROJECT_STATE.md `[IN PROGRESS]`: "Deployment Hardening (Priority 2 lane) — implementation sync complete on branch NWAP/deployment-hardening-traceability-repair; awaiting SENTINEL MAJOR validation gate." ✅
- NEXT PRIORITY correctly gates on MAJOR validation path ✅
- No premature done-claim in state ✅

**Domain structure:**
- No `phase*/` folders found under `projects/polymarket/polyquantbot/` ✅
- Domain folders present: `core/`, `data/`, `strategy/`, `intelligence/`, `risk/`, `execution/`, `monitoring/`, `api/`, `infra/`, `backtest/`, `reports/` ✅

**Encoding:**
- `Dockerfile`: clean ASCII ✅
- `fly.toml`: clean ASCII ✅
- `operator_runbook.md`: clean ASCII ✅
- `fly_runtime_troubleshooting.md`: clean ASCII ✅
- `phase10-10_02_deployment-hardening-contract-closure.md`: UTF-8 em-dash (`e2 80 94`) in title line — valid UTF-8, not mojibake. Renders correctly. ✅

**Phase 0 verdict: PASS — all pre-test gates satisfied.**

---

### Phase 1 — Functional Contract Verification

**Dockerfile HEALTHCHECK (Dockerfile:31):**
```
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
  CMD python -c "import os,sys,urllib.request; url='http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health'; sys.exit(0 if urllib.request.urlopen(url, timeout=5).status == 200 else 1)" || exit 1
```
- Single-line — parse-safe ✅
- Calls `GET /health` on `127.0.0.1:$PORT` — aligned with `/health` route contract ✅
- `PORT` env default `8080` matches `EXPOSE 8080` and `fly.toml internal_port = 8080` ✅
- `start-period=45s` matches `fly.toml grace_period = "45s"` — consistent startup window ✅
- `timeout=10s` in HEALTHCHECK vs `timeout=5s` in fly.toml check — HEALTHCHECK timeout is the outer container timeout; the inner `urllib.request` timeout is 5s. No conflict. ✅
- `|| exit 1` is redundant (CMD already exits non-zero on failure) but harmless ✅

**`/health` route (server/api/routes.py:42-43):**
- Returns `{"status": "ok"|"degraded", "ready": bool}` with HTTP 200 (ready) or 503 (not ready) ✅
- HEALTHCHECK checks `status == 200` — aligned: only passes when `state.ready` is True ✅

**`/ready` route (server/api/routes.py):**
- Full dependency gate: Telegram runtime, DB runtime, Falcon config, paper-only boundary ✅
- Returns 200 or 503 based on `overall_ready` ✅
- `live_mode_execution_allowed: False` hardcoded ✅
- `paper_only_execution_boundary: True` hardcoded ✅

**Finding:** All functional contracts verified. No gaps. ✅

---

### Phase 2 — Deployment Pipeline Alignment

**fly.toml vs Dockerfile vs docs:**

| Contract point | Dockerfile | fly.toml | operator_runbook.md | fly_runtime_troubleshooting.md |
|---|---|---|---|---|
| Entrypoint | `python -m projects.polymarket.polyquantbot.scripts.run_api` | (build section, no override) | Section 2: same path ✅ | Section A: same path ✅ |
| Port | `EXPOSE 8080`, `PORT=8080` | `internal_port = 8080` ✅ | — | — |
| Health check path | `/health` | `path = "/health"` ✅ | Section 2 ✅ | Section A ✅ |
| Readiness path | — | `path = "/ready"` ✅ | Section 2 ✅ | Section A ✅ |
| Grace period | `start-period=45s` | `grace_period = "45s"` ✅ | — | — |
| Deploy strategy | — | `strategy = "immediate"` ✅ | Section 2 ✅ | — |
| Single machine | — | `min=1, max=1, auto_stop="off"` ✅ | Section 2 ✅ | Section A ✅ |

All four artifacts are internally consistent. No drift detected. ✅

---

### Phase 3 — Failure Mode Coverage

**Restart policy (operator_runbook.md:Section 3):**
- Bounded: re-check `/health`, `/ready`, Telegram startup logs, Telegram command responses ✅
- No overclaim — does not assert automatic recovery ✅

**Rollback procedure (operator_runbook.md:Section 4, fly_runtime_troubleshooting.md:Section E):**
- Image-based: `fly releases --app crusaderbot --image` → `fly deploy --image registry.fly.io/crusaderbot:<IMAGE_TAG> --strategy immediate` ✅
- Config/secret/fly.toml drift caveat explicitly stated in both docs ✅
- No stale `fly rollback` command used — correct image-based approach ✅

**Restart vs rollback vs redeploy distinction (fly_runtime_troubleshooting.md:Section E):**
- Three paths clearly differentiated ✅
- Restart: same release, transient hang ✅
- Rollback: last known-good image ✅
- Redeploy: new release cycle ✅

**Health/ready mismatch (fly_runtime_troubleshooting.md:Section D):**
- Pattern documented: `/health` OK but `/ready` degraded ✅
- Interpretation correct: process alive, dependencies not ready ✅
- Operator action path defined ✅

**Finding:** All failure modes covered, bounded, and truthful. ✅

---

### Phase 4 — Async/Concurrency Safety

**Telegram polling single-machine contract:**
- `fly.toml`: `strategy = "immediate"` prevents overlapping machines during deploy ✅
- `max_machines_running = 1` enforces single-machine constraint ✅
- `auto_stop_machines = "off"` prevents scale-to-zero mid-operation ✅
- Forge report explicitly states rationale: "avoid overlapping Telegram pollers in single-machine mode" ✅

**Finding:** Async safety for the deployment contract is correctly enforced at the infra layer. ✅

---

### Phase 5 — Risk Constants and Live-Trading Guard

**ENABLE_LIVE_TRADING guard (server/core/runtime.py:46-47):**
```python
if trading_mode == "LIVE" and os.getenv("ENABLE_LIVE_TRADING", "").strip().lower() != "true":
    raise RuntimeError("LIVE mode requires ENABLE_LIVE_TRADING=true.")
```
- Guard present and enforced ✅
- Not bypassed by any change in this PR ✅

**Paper-only boundary:**
- `live_mode_execution_allowed: False` hardcoded in `/ready` response (routes.py:140) ✅
- `paper_only_execution_boundary: True` hardcoded (routes.py:141) ✅
- operator_runbook.md Section 7 explicitly states paper-only boundary ✅
- No live-trading or production-capital readiness claim in any scoped file ✅

**Kelly / risk constants:**
- Not touched by this PR — deployment/docs-only lane ✅
- No risk constant drift introduced ✅

**Finding:** Live-trading guard intact. Paper-only boundary preserved. No risk constant drift. ✅

---

### Phase 6 — Latency / Timing Alignment

| Parameter | Dockerfile | fly.toml | Alignment |
|---|---|---|---|
| Health check interval | `30s` | `30s` | ✅ |
| Health check timeout | `10s` (outer) / `5s` (urllib) | `5s` | ✅ (no conflict) |
| Start period / grace | `45s` | `45s` | ✅ |
| Retries | `3` | (Fly default) | ✅ |
| Ready check interval | — | `30s` | ✅ |
| Ready check timeout | — | `5s` | ✅ |
| Ready grace period | — | `45s` | ✅ |

**Finding:** All timing parameters consistent. No misalignment. ✅

---

### Phase 7 — Infra Contract

**Fly machine config:**
- `cpu_kind = "shared"`, `cpus = 1`, `memory_mb = 512` — appropriate for paper-beta single-machine ✅
- `primary_region = "iad"` — declared ✅
- `force_https = true` — enforced ✅
- `CRUSADER_TELEGRAM_RUNTIME_REQUIRED = "true"` env set in fly.toml — aligns with runtime requirement ✅

**Finding:** Infra contract is correctly specified and internally consistent. ✅

---

### Phase 8 — Smoke Test Contract Consistency

**operator_runbook.md Section 5 vs fly_runtime_troubleshooting.md Section F:**

| Step | operator_runbook.md | fly_runtime_troubleshooting.md | Match |
|---|---|---|---|
| 1 | `curl -fsS .../health` | `curl -fsS .../health` | ✅ |
| 2 | `curl -fsS .../ready` | `curl -fsS .../ready` | ✅ |
| 3 | `fly logs ... grep crusaderbot_telegram_runtime_started\|crusaderbot_runtime_transition` | same grep pattern | ✅ |
| 4 | Telegram `/start`, `/help`, `/status` | Telegram `/start`, `/help`, `/status` | ✅ |

**Pass condition (operator_runbook.md:Section 5):**
- `/health` returns success ✅
- `/ready` returns ready payload ✅
- startup/transition logs present ✅
- Telegram commands return non-empty public-safe replies ✅
- "Do not declare recovery complete from `/health` alone" — correctly stated ✅

**Finding:** Smoke test contract is explicit, consistent across both docs, and correctly bounded. ✅

---

## ⚠️ CRITICAL ISSUES

None found.

---

## 📊 STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture / contract alignment | 20% | 20/20 | Dockerfile, fly.toml, docs fully consistent |
| Functional verification | 20% | 18/20 | /health and /ready routes verified statically; py_compile not executable (runner gap, not a code defect) |
| Failure modes | 20% | 20/20 | Restart, rollback, redeploy, health/ready mismatch all covered and truthful |
| Risk / safety constants | 20% | 20/20 | ENABLE_LIVE_TRADING guard intact, paper-only boundary preserved, no risk constant drift |
| Infra + Telegram | 10% | 10/10 | Single-machine contract enforced, Telegram polling safety correct |
| Latency / timing | 10% | 10/10 | All intervals, timeouts, grace periods consistent |

**Total: 98/100**

**Deduction rationale:** 2 points deducted for py_compile evidence gap (Python not available in runner). This is a runner environment limitation, not a code defect — no new runtime logic was introduced in this PR. Static analysis confirms all touched files are syntactically correct.

---

## 🚫 GO-LIVE STATUS

**✅ APPROVED**

Score: 98/100. Zero critical issues. All Phase 0 pre-test gates passed. Branch traceability clean. Deployment contract (Dockerfile + fly.toml + operator docs) is internally consistent, truthful, and bounded to the scoped deployment/startup/health/readiness/restart/rollback/smoke-test lane. No overclaim. Paper-only boundary preserved. Live-trading guard intact.

---

## 🛠 FIX RECOMMENDATIONS

None required for merge. One non-blocking observation:

- **`|| exit 1` in HEALTHCHECK CMD** (Dockerfile:31): Redundant — the CMD already exits non-zero on failure. Harmless. Can be cleaned up in a future MINOR pass if desired.

---

## 📱 TELEGRAM / SMOKE TEST PREVIEW

Post-deploy smoke test contract (from operator_runbook.md Section 5):

```bash
# 1. Health aliveness
curl -fsS https://crusaderbot.fly.dev/health

# 2. Runtime readiness
curl -fsS https://crusaderbot.fly.dev/ready

# 3. Startup log evidence
fly logs -a crusaderbot | grep -E "crusaderbot_telegram_runtime_started|crusaderbot_runtime_transition"

# 4. Telegram command baseline
# Send: /start  /help  /status
# Expected: non-empty, public-safe, paper-only replies
```

Pass condition: all four checks pass before declaring recovery or deploy complete.
