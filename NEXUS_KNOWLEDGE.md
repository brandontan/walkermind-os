# NEXUS KNOWLEDGE FILE
# Walker AI Trading Team — Full Reference
# NEXUS reads this file before every task via GitHub connector
# Repo: https://github.com/bayuewalker/walker-ai-team

---

## DOMAIN STRUCTURE (11 FOLDERS — LOCKED)

All code must exist ONLY within:
```
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

No phase*/ folders. No files outside these 11 folders. No exceptions.

---

## REPORT NAMING — VALID vs INVALID

Format: [phase]_[increment]_[name].md (forge/sentinel) or .html (briefer)

| Valid ✅ | Invalid ❌ |
|---|---|
| 10_8_signal_activation.md | FORGE-X_PHASE10.md |
| 11_1_cleanup.md | PHASE10.md |
| 24_1_validation_engine_core.md | report.md |
| 24_1_validation_report.html | structure_refactor.md |

---

## BRANCH NAMING

| Agent | Format | Example |
|---|---|---|
| FORGE-X | feature/forge/[task-name] | feature/forge/kelly-risk-module |
| SENTINEL | feature/sentinel/[phase]-[inc]-[name] | feature/sentinel/24-1-validation |
| BRIEFER | feature/briefer/[phase]-[inc]-[name] | feature/briefer/24-1-investor-report |

Rules: lowercase, hyphens only, no spaces, max 50 chars.

---

## PROJECT_STATE.md — 5 UPDATABLE SECTIONS

FORGE-X updates ONLY these after every task:
```
Last Updated  : [YYYY-MM-DD]
Status        : [current phase description]
COMPLETED     : [newly completed items from this task]
IN PROGRESS   : [ongoing items, if any]
NOT STARTED   : [remaining roadmap items]
NEXT PRIORITY : [immediate next step for COMMANDER]
KNOWN ISSUES  : [any issues found during this task]
```
Commit: "update: project state after [task name]"
Never modify other sections. Never rewrite entire file.

---

## RISK RULES — FIXED VALUES (never change anywhere)

| Rule | Value |
|---|---|
| Kelly fraction α | 0.25 — fractional only. α=1.0 FORBIDDEN. |
| Max position size | ≤ 10% of total capital |
| Max concurrent trades | 5 |
| Daily loss limit | −$2,000 hard stop |
| Max drawdown | > 8% → system stop |
| Liquidity minimum | $10,000 orderbook depth |
| Signal deduplication | Required on every order |
| Kill switch | Mandatory — must be testable |
| Arbitrage | Execute only if net_edge > fees + slippage AND > 2% |

---

## QUANT FORMULAS

```
EV       = p·b − (1−p)
edge     = p_model − p_market
Kelly    = (p·b − q) / b  →  always 0.25f
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
| Secrets | .env only — never hardcoded |
| Operations | Idempotent — safe to retry |
| Resilience | Retry with backoff + timeout on all external calls |
| Logging | structlog — structured JSON |
| Errors | Zero silent failures — every exception caught and logged |
| Pipeline | timeout + retry + dedup + DLQ on every pipeline |
| Database | PostgreSQL + Redis + InfluxDB |

---

## COPILOT PR BLOCKING CONDITIONS

Any single one = 🚫 BLOCKED:

| Code | Condition |
|---|---|
| B1 | FORGE-X report missing from reports/forge/ |
| B2 | Report naming format incorrect |
| B3 | Report missing any of 6 mandatory sections |
| B4 | PROJECT_STATE.md not updated in PR |
| B5 | Any phase*/ folder present |
| B6 | File outside 11 domain folders |
| B7 | Hardcoded secret / API key |
| B8 | Full Kelly (α=1.0) used |
| B9 | RISK layer bypassed before EXECUTION |
| B10 | Bare except: pass or silent exception |
| B11 | import threading present |
| B12 | ENABLE_LIVE_TRADING guard bypassed |

---

## SENTINEL — STABILITY SCORE RUBRIC

| Category | Weight | Full Points | Partial (50%) | Zero + BLOCKED |
|---|---|---|---|---|
| Architecture | 20% | All checks pass | Minor issues | Any critical violation |
| Functional | 20% | All modules pass | Edge cases fail | Core logic broken |
| Failure modes | 20% | All 8 pass | Some warn | Any crash |
| Risk rules | 20% | All in code | Config only | Any rule missing |
| Infra+Telegram | 10% | All connected + alerts | Partial | Services down |
| Latency | 10% | All targets met | Some warnings | All exceeded 2x |

---

## SENTINEL — ENVIRONMENT RULES

| Service | dev | staging | prod |
|---|---|---|---|
| Redis | warn only | ENFORCED | ENFORCED |
| PostgreSQL | warn only | ENFORCED | ENFORCED |
| Telegram | warn only | ENFORCED | ENFORCED |

---

## SENTINEL — TELEGRAM REQUIRED ALERT EVENTS (all 7 must fire)

| Event | Required |
|---|---|
| System error | ✅ |
| Execution blocked | ✅ |
| Latency warning | ✅ |
| Slippage warning | ✅ |
| Kill switch triggered | ✅ |
| WebSocket reconnect | ✅ |
| Hourly checkpoint | ✅ |

---

## BRIEFER — TEMPLATE SELECTION TABLE

| Report Type | Audience | Template |
|---|---|---|
| Internal: phase completion, validation, health, bug, backtest | Team | TPL_INTERACTIVE_REPORT.html |
| Client: progress, sprint delivery, go-live readiness | Client | TPL_INTERACTIVE_REPORT.html |
| Investor: phase update, performance | Investor | TPL_INTERACTIVE_REPORT.html |
| Investor: capital deployment, risk transparency | Investor | REPORT_TEMPLATE_MASTER.html |
| Any — print / PDF | Any | REPORT_TEMPLATE_MASTER.html |

---

## BRIEFER — TPL_INTERACTIVE FULL PLACEHOLDER REFERENCE

| Placeholder | Replace With |
|---|---|
| {{REPORT_TITLE}} | e.g. Investor Update Phase 24.1 |
| {{REPORT_CODENAME}} | e.g. Phase 24.1 |
| {{REPORT_FOCUS}} | e.g. Validation Engine Core |
| {{SYSTEM_NAME}} | PolyQuantBot |
| {{OWNER}} | Bayue Walker |
| {{REPORT_DATE}} | e.g. April 2026 |
| {{SYSTEM_STATUS}} | e.g. PAPER_ACTIVE |
| {{BADGE_1_LABEL}} | e.g. Confidential |
| {{BADGE_2_LABEL}} | e.g. Paper Trading |
| {{TAB_1_LABEL}}…{{TAB_4_LABEL}} | e.g. OVERVIEW |
| {{TAB_1_HEADING}} | e.g. Executive Summary |
| {{NOTICE_TEXT}} | Disclaimer / notice text |
| {{M1_LABEL}}…{{M8_LABEL}} | Metric card labels |
| {{M1_VALUE}}…{{M8_VALUE}} | Metric card values |
| {{M1_NOTE}}…{{M8_NOTE}} | Metric card notes |
| {{PROG_1_LABEL}} / {{PROG_1_PCT}} | Progress bar label + % (number only) |
| {{PROG_TOTAL_LABEL}} / {{PROG_TOTAL_VALUE}} | Total row |
| {{LIST_1_LABEL}} / {{LIST_1_VALUE}} | Data list rows |
| {{S1_PHASE}} / {{S1_MODULE}} / {{S1_VERDICT}} | SENTINEL table rows |
| {{LIMIT_1_TITLE}} / {{LIMIT_1_DESC}} | Known limitations |
| {{FOOTER_DISCLAIMER}} | Footer disclaimer text |

---

## BRIEFER — COMPONENT CLASSES (TPL_INTERACTIVE)

Metric cards: success (green) / warn (amber) / accent (cyan) / danger (red) / muted (gray) / info (blue)
Badges: badge-accent / badge-warn / badge-success / badge-danger / badge-muted
Pipeline nodes: pipe-active (cyan) / pipe-success (green) / pipe-warn (amber) / pipe-inactive (gray)
Notice boxes: notice-warn / notice-success / notice-info / notice-danger
Checklist: default ✓ / .warn ! / .error ✗ / .next › / .info ·
File tags: tag-new (green) / tag-mod (cyan) / tag-del (red)
SENTINEL verdict: td-success / td-warn / td-danger

---

## BRIEFER — REPORT_TEMPLATE_MASTER PLACEHOLDERS

| Placeholder | Replace With |
|---|---|
| {{REPORT_TITLE}} | Report title |
| {{REPORT_CODENAME}} | System codename |
| {{REPORT_DATE}} | Date |
| {{CONFIDENTIALITY_LABEL}} | e.g. Confidential — Authorized Recipients Only |
| {{SYSTEM_NAME}} | PolyQuantBot |
| {{OWNER}} | Bayue Walker |
| {{PHASE_LABEL}} | Phase number and name |
| {{MODE_LABEL}} | e.g. Live Stage 1 (Paper Capital) |
| {{MODE_PILL_CLASS}} | pill-green / pill-orange / pill-red / pill-blue |
| {{DISCLAIMER_TEXT}} | Full disclaimer |
| {{FOOTER_DISCLAIMER}} | Footer legal text |

KV box classes: positive (green) / neutral (amber) / negative (red) / info (cyan)
Pill classes: pill-green / pill-orange / pill-red / pill-blue
Milestone dots: dot-done / dot-active / dot-pending / dot-future
Risk card classes: default amber / .red critical / .green resolved

Available sections (add/remove as needed):
Executive Summary + KV metrics / System Overview + Pipeline + Status table /
Performance Summary + progress bar / Data / Activity table /
Risk & Limitations / System Strengths / Next Milestones / SENTINEL History / Checklist

---

## BRIEFER — RISK CONTROLS TABLE (FIXED in every report)

| Rule | Value |
|---|---|
| Kelly Fraction (α) | 0.25 — fractional only |
| Max Position Size | ≤ 10% of total capital |
| Daily Loss Limit | −$2,000 hard stop |
| Drawdown Circuit-Breaker | > 8% → auto-halt |
| Signal Deduplication | Per (market, side, price, size) |
| Kill Switch | Telegram-accessible, immediate halt |

Only add phase-specific rows BELOW these fixed rows. Never change fixed values.

---

## BRIEFER — ENCODING RULES (CRITICAL for GitHub write)

When writing HTML or markdown to GitHub:
- Preserve ALL newlines and indentation before encoding
- Never minify HTML before encoding
- Never collapse markdown to a single line
- Every heading on its own line with blank line before and after
- Every bullet item on its own line
- Sections separated by blank lines

Wrong: content = "# TITLE ## Phase0 - item1 - item2 ## Score"
Right: content = "# TITLE\n\n## Phase 0\n- item1\n- item2\n\n## Score"

---

## TEAM WORKFLOW

```
COMMANDER → generates task
    ↓
FORGE-X → builds → commits → opens PR
    ↓
Copilot → auto-reviews PR (blocks on 12 conditions)
    ↓
COMMANDER → requests SENTINEL validation
    ↓
SENTINEL → validates → issues verdict → saves report → opens PR
    ↓
COMMANDER → requests BRIEFER report (if needed)
    ↓
BRIEFER → transforms report → saves HTML → opens PR
    ↓
COMMANDER → reviews all PRs → decides merge
```

None of the three agents merge PRs directly. COMMANDER decides.

---

## INTELLIGENCE LAYER

- News sentiment + drift detection
- Bayesian probability updates
- External API: narrative.agent.heisenberg.so

---

## BUILD ROADMAP

Phase 1 — Foundation  : setup, repo, connections, infra
Phase 2 — Strategy    : signals, sizing, backtest
Phase 3 — Intelligence: engine, risk, scanner
Phase 4 — Production  : deploy, dashboard, confirm
