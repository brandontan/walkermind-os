# NEXUS KNOWLEDGE FILE — FULL HARDENED REFERENCE
# Walker AI Trading Team
# Mistral version aligned with NEXUS
# Repo: https://github.com/bayuewalker/walker-ai-team

---

## REPO

https://github.com/bayuewalker/walker-ai-team

---

## CORE PRINCIPLE

Single source of truth:

- `PROJECT_STATE.md` → current system state
- `projects/polymarket/polyquantbot/reports/forge/` → build truth
- `projects/polymarket/polyquantbot/reports/sentinel/` → validation truth
- `projects/polymarket/polyquantbot/reports/briefer/` → communication layer

Important:

- FORGE-X report is reference, not proof
- SENTINEL must verify against actual code
- If code and report disagree, code wins and report is marked incorrect
- Never rely on memory alone

---

## DOMAIN STRUCTURE (11 FOLDERS — LOCKED)

All code must exist ONLY within:

```text
core/           — shared utilities, base classes
data/           — data ingestion, feed handling
strategy/       — signal generation, market logic
intelligence/   — Bayesian EV, ML models
risk/           — Kelly sizing, position limits, kill switch
execution/      — order placement, fills, dedup
monitoring/     — logging, metrics, health checks
api/            — external API interfaces
infra/          — infrastructure, config, env
backtest/       — backtesting engine, historical simulation
reports/
├── forge/      — FORGE-X reports (.md)
├── sentinel/   — SENTINEL reports (.md)
└── briefer/    — BRIEFER HTML reports (.html)
```

Rules:
- No `phase*/` folders anywhere in repo
- No files outside these 11 folders except repo-root metadata/config files
- No legacy path retention
- No shims or compatibility layers
- No exceptions without explicit COMMANDER approval

---

## KEY FILE LOCATIONS (FULL PATHS)

```text
PROJECT_STATE.md
docs/CLAUDE.md
docs/KNOWLEDGE_BASE.md
docs/templates/TPL_INTERACTIVE_REPORT.html
docs/templates/REPORT_TEMPLATE_MASTER.html

projects/polymarket/polyquantbot/
projects/polymarket/polyquantbot/reports/forge/
projects/polymarket/polyquantbot/reports/sentinel/
projects/polymarket/polyquantbot/reports/briefer/

projects/tradingview/indicators/
projects/tradingview/strategies/
projects/mt5/ea/
projects/mt5/indicators/
```

---

## BRANCH NAMING (FINAL — MISTRAL SAFE)

Use:

```text
feature/{feature}-{date}
```

Examples:
- `feature/execution-order-engine-20260406`
- `feature/risk-drawdown-circuit-20260406`
- `feature/report-investor-update-20260406`
- `feature/validation-phase9-audit-20260406`

Rules:
- lowercase only
- hyphen-separated
- no spaces
- do not use `[` or `]`
- do not use old formats like `feature/forge/[task-name]`
- `{feature}` should resolve to concise `area-purpose`
- `{date}` is required for uniqueness

---

## REPORT NAMING — VALID vs INVALID

Format:
- Forge / Sentinel: `[phase]_[increment]_[name].md`
- Briefer: `[phase]_[increment]_[name].html`

Valid:
- `10_8_signal_activation.md`
- `11_1_cleanup.md`
- `24_1_validation_engine_core.md`
- `24_1_validation_report.html`

Invalid:
- `FORGE-X_PHASE10.md`
- `PHASE10.md`
- `report.md`
- `structure_refactor.md`

---

## FORGE-X REPORT — 6 MANDATORY SECTIONS

Every FORGE-X report MUST contain all 6 sections:

1. What was built
2. Current system architecture
3. Files created / modified (full paths)
4. What is working
5. Known issues
6. What is next

Missing any section:
→ report invalid
→ task incomplete
→ SENTINEL must not proceed

---

## HARD COMPLETION RULE (CRITICAL)

A FORGE-X task is INVALID if ANY of the following is missing:

- report not saved in `projects/polymarket/polyquantbot/reports/forge/`
- report naming format incorrect
- report missing any of the 6 mandatory sections
- `PROJECT_STATE.md` not updated
- report path not explicitly included in final output
- code + report + state not committed together

System behavior:
- No valid FORGE report → no SENTINEL
- No valid SENTINEL → no merge
- No report = no system memory
- No system memory = no trustworthy validation

---

## PROJECT_STATE.md — UPDATABLE SECTIONS

FORGE-X updates ONLY these sections after every build task:

```text
Last Updated
Status
COMPLETED
IN PROGRESS
NOT STARTED
NEXT PRIORITY
KNOWN ISSUES
```

Rules:
- Never rewrite other sections
- Never replace the whole file if only these fields need change
- Commit message:
  `update: project state after [task name]`

---

## PIPELINE (LOCKED)

```text
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
```

Rules:
- RISK must always precede EXECUTION
- No stage may be skipped
- MONITORING must receive events from every stage
- No execution path may bypass risk checks

---

## RISK RULES — FIXED VALUES (NEVER CHANGE)

| Rule | Value |
|---|---|
| Kelly fraction α | 0.25 — fractional only. α=1.0 FORBIDDEN |
| Max position size | ≤ 10% of total capital |
| Max concurrent trades | 5 |
| Daily loss limit | −$2,000 hard stop |
| Max drawdown | > 8% → system stop |
| Liquidity minimum | $10,000 orderbook depth |
| Signal deduplication | Required on every order |
| Kill switch | Mandatory — must be testable |
| Arbitrage | Execute only if `net_edge > fees + slippage` AND `> 2%` |

If code, report, or output conflicts with these values:
→ treat as drift or critical violation

---

## QUANT FORMULAS

```text
EV       = p·b − (1−p)
edge     = p_model − p_market
Kelly    = (p·b − q) / b  → always 0.25f
Signal S = (p_model − p_market) / σ
MDD      = (Peak − Trough) / Peak
VaR      = μ − 1.645σ  (CVaR monitored)
```

---

## ENGINEERING STANDARDS

| Standard | Requirement |
|---|---|
| Language | Python 3.11+ full type hints |
| Concurrency | asyncio only — no threading |
| Secrets | `.env` only — never hardcoded |
| Operations | Idempotent — safe to retry |
| Resilience | Retry with backoff + timeout on all external calls |
| Logging | `structlog` — structured JSON |
| Errors | Zero silent failures — every exception caught and logged |
| Pipeline | timeout + retry + dedup + DLQ on every pipeline |
| Database | PostgreSQL + Redis + InfluxDB |

Additional enforcement:
- no `except: pass`
- no swallowed exceptions
- no placeholder implementations presented as complete

---

## COPILOT PR BLOCKING CONDITIONS

Any single condition = 🚫 BLOCKED:

| Code | Condition |
|---|---|
| B1 | FORGE-X report missing from `reports/forge/` |
| B2 | Report naming format incorrect |
| B3 | Report missing any mandatory section |
| B4 | `PROJECT_STATE.md` not updated in PR |
| B5 | Any `phase*/` folder present |
| B6 | File outside allowed domain folders |
| B7 | Hardcoded secret / API key |
| B8 | Full Kelly (α=1.0) used |
| B9 | RISK layer bypassed before EXECUTION |
| B10 | `except: pass` or silent exception |
| B11 | `import threading` present |
| B12 | `ENABLE_LIVE_TRADING` guard bypassed |

---

## SENTINEL — DEFAULT STATE

System is UNSAFE by default.

Sentinel goal:
- not to assume safety
- not to trust reports blindly
- to prove safety with evidence

If safety cannot be proven:
→ FAIL
→ score 0 for affected category
→ BLOCKED if critical

Sentinel is not a reviewer.
Sentinel is a breaker.

---

## SENTINEL — EVIDENCE RULE (CRITICAL)

Every validation finding MUST include:

- file path
- exact line number or line range
- code snippet (minimum 3 lines where possible)
- reason
- severity

If evidence is missing:
- score = 0 for that category
- mark category as FAILURE
- do not award full points
- do not use “assumed”, “likely”, “appears fine” as a substitute for proof

FORGE report is not enough.
Actual code verification is required.

---

## SENTINEL — PRE-TEST PHASES (FAIL FAST)

### Phase 0A — Forge Report Validation
Verify:
- report exists in correct path
- naming correct
- all 6 sections present

If not:
→ STOP
→ BLOCKED

### Phase 0B — PROJECT_STATE Freshness
Verify:
- `PROJECT_STATE.md` updated after relevant FORGE task

If not:
→ FAILURE
→ report before proceeding

### Phase 0C — Architecture Scan
Verify:
- no `phase*/` folders
- no legacy imports from `phase*/`
- all code in locked domain structure
- no duplicate logic introduced unnecessarily

Any critical architecture violation:
→ BLOCKED

### Phase 0D — FORGE-X Compliance
Verify:
- moved files were deleted from old location
- no shims
- no re-exports
- report saved correctly

Violations:
→ failure per item

### Phase 0E — Implementation Evidence Check (NEW)
For critical layers, verify actual implementation exists and is used:

- risk
- execution
- data validation
- monitoring hooks

If code cannot be located, is placeholder-only, or is not actually wired into pipeline:
→ STOP
→ BLOCKED
→ reason: `No implementation evidence found`

---

## SENTINEL — VALIDATION PHASES

### Phase 1 — Functional Testing
Test each relevant module in isolation:
- input validation works
- output contract matches
- explicit error handling exists
- async functions do not block event loop

### Phase 2 — End-to-End Pipeline
Validate full flow:
`DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING`

Verify:
- each stage passes correct data shape
- no stage bypass possible
- RISK cannot be skipped
- MONITORING receives all stage events

### Phase 3 — Failure Mode Testing
Mandatory scenarios:
- API failure
- WebSocket disconnect
- request timeout
- order rejection
- partial fill
- stale data
- latency spike
- duplicate signals

Every scenario requires reproducible result.
“Seems to work” = failure.

### Phase 4 — Async Safety
Verify:
- no race conditions
- no shared state corruption
- deterministic ordering where required
- no fire-and-forget tasks without error handling

### Phase 5 — Risk Validation (STRICT)
For EACH risk rule, Sentinel must show:
- file
- line
- snippet
- enforcement logic
- trigger condition

Missing evidence for ANY rule:
→ CRITICAL
→ BLOCKED

### Phase 6 — Latency Validation
Must include:
- measured value
- measurement method

Examples:
- timestamp diff
- benchmark harness
- traced event timing

If no actual measurement:
→ score = 0 for latency

### Phase 7 — Infra Validation
Environment-dependent:
- `dev` → warn only for infra/Telegram
- `staging` / `prod` → enforced

Verify:
- Redis
- PostgreSQL
- Telegram
- credentials loaded from `.env`
- connection not just configured, but responding

### Phase 8 — Telegram Validation
Skip only in `dev`.

All 7 alert events must be tested:
- System error
- Execution blocked
- Latency warning
- Slippage warning
- Kill switch triggered
- WebSocket reconnect
- Hourly checkpoint

Missing event or undelivered alert:
→ fail
→ critical if staging/prod

---

## SENTINEL — NEGATIVE TEST REQUIREMENT

For every critical subsystem, Sentinel MUST attempt to break:

- invalid input
- missing data
- API failure
- concurrency conflict
- stale state
- wrong environment configuration when relevant

If no negative testing is performed for a critical subsystem:
→ category failure
→ do not award full score

---

## SENTINEL — STABILITY SCORE RUBRIC

| Category | Weight | Full Points | Partial (50%) | Zero + BLOCKED |
|---|---|---|---|---|
| Architecture | 20 | All checks pass with evidence | Minor issues with evidence | Any critical violation or no evidence |
| Functional | 20 | All core modules verified | Partial pass / edge failures | Core logic broken or unverified |
| Failure modes | 20 | All required scenarios verified | Some pass / some warn | Any crash, hang, or no evidence |
| Risk rules | 20 | Every rule verified in code | Partial enforcement | Any missing rule or no evidence |
| Infra + Telegram | 10 | All connected + alerts verified | Partial | Required services down or unverified |
| Latency | 10 | Measured and within target | Measured with warnings | Unmeasured or major failure |

Scoring rule:
- full score only if evidence exists and implementation verified
- partial only if partial evidence exists
- no evidence = 0

Any 0 in a critical category:
→ BLOCKED

---

## SENTINEL — ANTI FALSE POSITIVE RULE

If total score = 100:

Sentinel report MUST include at least:
- 5 distinct file references
- 5 code snippets
- explicit evidence across multiple categories

If not:
- reduce score by 30
- mark status: `SUSPICIOUS VALIDATION`
- explain why score was reduced

Default expectation:
real systems usually produce a mix of passes, warnings, or follow-up items.
Perfect 100 without dense evidence is suspicious.

---

## SENTINEL — CRITICAL ISSUE DEFINITION

Any of the following is CRITICAL:

- missing implementation
- missing risk rule
- missing async safety on critical path
- missing failure handling
- no evidence for critical claim
- placeholder logic presented as complete
- RISK bypass before EXECUTION
- live-trading guard bypass
- hardcoded secrets
- threading in async system

Any critical issue:
→ BLOCKED

---

## SENTINEL — VERDICT

| Verdict | Condition |
|---|---|
| APPROVED | Score ≥ 85 and zero critical issues |
| CONDITIONAL | Score 60–84 and zero critical issues |
| BLOCKED | Score < 60 OR any critical issue OR Phase 0 failure |

Any single critical issue = BLOCKED.
No exceptions.

---

## SENTINEL — REPORT REQUIREMENTS

Path:
`projects/polymarket/polyquantbot/reports/sentinel/[phase]_[increment]_[name].md`

Report must contain:
- environment
- Phase 0 results
- findings by category
- evidence references
- score breakdown
- critical issues
- verdict
- reasoning
- prioritized fix recommendations
- Telegram visual preview when applicable

No vague summaries.
Every serious finding must be traceable.

---

## BRIEFER — TEMPLATE SELECTION TABLE

| Report Type | Audience | Template |
|---|---|---|
| Internal: phase completion, validation, health, bug, backtest | Team | `TPL_INTERACTIVE_REPORT.html` |
| Client: progress, sprint delivery, go-live readiness | Client | `TPL_INTERACTIVE_REPORT.html` |
| Investor: phase update, performance | Investor | `TPL_INTERACTIVE_REPORT.html` |
| Investor: capital deployment, risk transparency | Investor | `REPORT_TEMPLATE_MASTER.html` |
| Any — print / PDF | Any | `REPORT_TEMPLATE_MASTER.html` |

Decision rule:
- Browser / device → `TPL_INTERACTIVE_REPORT.html`
- Print / PDF / formal → `REPORT_TEMPLATE_MASTER.html`
- Not specified → default interactive

---

## BRIEFER — TPL_INTERACTIVE FULL PLACEHOLDER REFERENCE

| Placeholder | Replace With |
|---|---|
| `{{REPORT_TITLE}}` | e.g. Investor Update Phase 24.1 |
| `{{REPORT_CODENAME}}` | e.g. Phase 24.1 |
| `{{REPORT_FOCUS}}` | e.g. Validation Engine Core |
| `{{SYSTEM_NAME}}` | PolyQuantBot |
| `{{OWNER}}` | Bayue Walker |
| `{{REPORT_DATE}}` | e.g. April 2026 |
| `{{SYSTEM_STATUS}}` | e.g. PAPER_ACTIVE |
| `{{BADGE_1_LABEL}}` | e.g. Confidential |
| `{{BADGE_2_LABEL}}` | e.g. Paper Trading |
| `{{TAB_1_LABEL}}…{{TAB_4_LABEL}}` | e.g. OVERVIEW |
| `{{TAB_1_HEADING}}` | e.g. Executive Summary |
| `{{NOTICE_TEXT}}` | Disclaimer / notice text |
| `{{M1_LABEL}}…{{M8_LABEL}}` | Metric card labels |
| `{{M1_VALUE}}…{{M8_VALUE}}` | Metric card values |
| `{{M1_NOTE}}…{{M8_NOTE}}` | Metric card notes |
| `{{PROG_1_LABEL}} / {{PROG_1_PCT}}` | Progress bar label + % (number only) |
| `{{PROG_TOTAL_LABEL}} / {{PROG_TOTAL_VALUE}}` | Total row |
| `{{LIST_1_LABEL}} / {{LIST_1_VALUE}}` | Data list rows |
| `{{S1_PHASE}} / {{S1_MODULE}} / {{S1_VERDICT}}` | SENTINEL table rows |
| `{{LIMIT_1_TITLE}} / {{LIMIT_1_DESC}}` | Known limitations |
| `{{FOOTER_DISCLAIMER}}` | Footer disclaimer text |

---

## BRIEFER — COMPONENT CLASSES (TPL_INTERACTIVE)

- Metric cards: `success` / `warn` / `accent` / `danger` / `muted` / `info`
- Badges: `badge-accent` / `badge-warn` / `badge-success` / `badge-danger` / `badge-muted`
- Pipeline nodes: `pipe-active` / `pipe-success` / `pipe-warn` / `pipe-inactive`
- Notice boxes: `notice-warn` / `notice-success` / `notice-info` / `notice-danger`
- Checklist: default ✓ / `.warn` ! / `.error` ✗ / `.next` › / `.info` ·
- File tags: `tag-new` / `tag-mod` / `tag-del`
- SENTINEL verdict cells: `td-success` / `td-warn` / `td-danger`

---

## BRIEFER — REPORT_TEMPLATE_MASTER PLACEHOLDERS

| Placeholder | Replace With |
|---|---|
| `{{REPORT_TITLE}}` | Report title |
| `{{REPORT_CODENAME}}` | System codename |
| `{{REPORT_DATE}}` | Date |
| `{{CONFIDENTIALITY_LABEL}}` | e.g. Confidential — Authorized Recipients Only |
| `{{SYSTEM_NAME}}` | PolyQuantBot |
| `{{OWNER}}` | Bayue Walker |
| `{{PHASE_LABEL}}` | Phase number and name |
| `{{MODE_LABEL}}` | e.g. Live Stage 1 (Paper Capital) |
| `{{MODE_PILL_CLASS}}` | `pill-green` / `pill-orange` / `pill-red` / `pill-blue` |
| `{{DISCLAIMER_TEXT}}` | Full disclaimer |
| `{{FOOTER_DISCLAIMER}}` | Footer legal text |

Additional classes:
- KV boxes: `positive` / `neutral` / `negative` / `info`
- Pill classes: `pill-green` / `pill-orange` / `pill-red` / `pill-blue`
- Milestone dots: `dot-done` / `dot-active` / `dot-pending` / `dot-future`
- Risk card classes: default amber / `.red` / `.green`

---

## BRIEFER — RISK CONTROLS TABLE (FIXED IN EVERY REPORT)

| Rule | Value |
|---|---|
| Kelly Fraction (α) | 0.25 — fractional only |
| Max Position Size | ≤ 10% of total capital |
| Daily Loss Limit | −$2,000 hard stop |
| Drawdown Circuit-Breaker | > 8% → auto-halt |
| Signal Deduplication | Per `(market, side, price, size)` |
| Kill Switch | Telegram-accessible, immediate halt |

Only add phase-specific rows BELOW these fixed rows.
Never change fixed values.

---

## BRIEFER — ENCODING RULES (CRITICAL FOR GITHUB WRITE)

When writing HTML or markdown:
- preserve all newlines and indentation
- never minify before encoding
- never collapse markdown to a single line
- every heading on its own line
- every bullet on its own line
- blank line between sections

Wrong:
`# TITLE ## Phase0 - item1 - item2 ## Score`

Right:
```text
# TITLE

## Phase 0
- item1
- item2

## Score
```

---

## TEAM WORKFLOW

```text
COMMANDER → generates task
    ↓
FORGE-X → builds → commits → opens PR
    ↓
Copilot → auto-reviews PR
    ↓
COMMANDER → requests SENTINEL validation
    ↓
SENTINEL → validates → issues verdict → saves report → opens PR
    ↓
COMMANDER → requests BRIEFER output if needed
    ↓
BRIEFER → transforms reports → saves HTML → opens PR
    ↓
COMMANDER → reviews all PRs → decides merge
```

Rules:
- none of the three agents merge PRs directly
- COMMANDER decides
- BRIEFER must not outrun validation when validation is required

---

## INTELLIGENCE LAYER

- News sentiment + drift detection
- Bayesian probability updates
- External API: `narrative.agent.heisenberg.so`

---

## BUILD ROADMAP

```text
Phase 1 — Foundation   : setup, repo, connections, infra
Phase 2 — Strategy     : signals, sizing, backtest
Phase 3 — Intelligence : engine, risk, scanner
Phase 4 — Production   : deploy, dashboard, confirm
```
