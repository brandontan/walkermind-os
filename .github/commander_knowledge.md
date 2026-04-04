## COMMANDER KNOWLEDGE FILE
- Attach as knowledge document in Custom GPT.

# Instructions always reads this before responding.

---

## REPO

```
https://github.com/bayuewalker/walker-ai-team
```

---

## KEY FILE LOCATIONS (FULL PATHS)

```
PROJECT_STATE.md                                                    ← repo root
docs/CLAUDE.md                                                      ← agent rules
docs/KNOWLEDGE_BASE.md                                              ← system knowledge
docs/pico.pdf                                                       ← reference
docs/advancee_trade_strategy.pdf                                    ← reference
docs/templates/TPL_INTERACTIVE_REPORT.html                          ← BRIEFER (browser)
docs/templates/REPORT_TEMPLATE_MASTER.html                          ← BRIEFER (PDF)

projects/polymarket/polyquantbot/                                   ← main bot
projects/polymarket/polyquantbot/reports/forge/                     ← FORGE-X reports
projects/polymarket/polyquantbot/reports/sentinel/                  ← SENTINEL reports
projects/polymarket/polyquantbot/reports/briefer/                   ← BRIEFER HTML reports
projects/tradingview/indicators/
projects/tradingview/strategies/
projects/mt5/ea/
projects/mt5/indicators/
```

---

## GITHUB ACTIONS — FULL REFERENCE

All 8 available actions. Always use actions — never open GitHub URLs directly.

### READ
```
getRepoContents(path, ref?)
```
- File → returns base64-encoded content (decode to read)
- Directory → returns array of {name, path, type, size}
- Examples:
  - getRepoContents("PROJECT_STATE.md")
  - getRepoContents("projects/polymarket/polyquantbot/reports/forge")
  - getRepoContents("projects/polymarket/polyquantbot/reports/forge/23_1_report.md")

### WRITE WORKFLOW
Step 1: `getRepoBranch("main")` → get latest commit SHA from response
Step 2: `createBranch("refs/heads/feature/[name]", sha)`
Step 3: `writeRepoFile(path, message, content_b64, sha?, branch)`
  - `content` must be base64-encoded (UTF-8 text → base64)
  - `sha` required only when UPDATING existing file (get from getRepoContents first)
  - `branch` = target branch name e.g. "feature/briefer/23-1-report"
Step 4: `createPullRequest(title, head, base="main", body)`

### PR MANAGEMENT
```
listPullRequests(state="open")       ← list PRs, check Copilot review
createPullRequest(title, head, base, body)
mergePullRequest(pull_number)        ← only after founder confirms
addPRComment(issue_number, body)     ← post SENTINEL verdict or QC notes
```

### BEFORE EVERY SESSION
```
1. getRepoContents("PROJECT_STATE.md") → decode base64 → read
2. getRepoContents("projects/polymarket/polyquantbot/reports/forge") → get file list → pick latest
3. getRepoContents("[latest forge report full path]") → decode → read
```

---

## DOMAIN STRUCTURE (11 FOLDERS — LOCKED)

All code must live within these folders only:

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
├── forge/      — FORGE-X completion reports (.md)
├── sentinel/   — SENTINEL validation reports (.md)
└── briefer/    — BRIEFER HTML reports (.html)
```

No `phase*/` folders. No files outside these folders. No exceptions.

---

## BRANCH NAMING

| Agent | Format | Example |
|---|---|---|
| FORGE-X | `feature/forge/[task-name]` | `feature/forge/kelly-risk-module` |
| BRIEFER | `feature/briefer/[task-name]` | `feature/briefer/23-1-investor-report` |
| SENTINEL | same branch as FORGE-X being validated | — |

Rules: lowercase, hyphens only, no spaces, max 50 chars.

---

## REPORT NAMING FORMAT

```
Forge & Sentinel : [phase]_[increment]_[name].md
Briefer          : [phase]_[increment]_[name].html
```

| Valid ✅ | Invalid ❌ |
|---|---|
| `10_8_signal_activation.md` | `FORGE-X_PHASE10.md` |
| `11_1_cleanup.md` | `report/FORGE-X_PHASE.md` |
| `23_1_ui_v3_paper_activation.md` | `report.md` |
| `23_1_ui_v3_paper_activation.html` | `structure_refactor.md` |

---

## FORGE-X REPORT — 6 MANDATORY SECTIONS

1. What was built
2. Current system architecture
3. Files created / modified (full paths)
4. What is working
5. Known issues
6. What is next

---

## PROJECT_STATE.md — 5 UPDATABLE SECTIONS

FORGE-X updates ONLY these after every task:
- `STATUS`
- `COMPLETED`
- `IN PROGRESS`
- `NEXT PRIORITY`
- `KNOWN ISSUES`

Never rewrite other sections.
Commit: `"update: project state after [task name]"`

---

## SENTINEL — 8 VALIDATION PHASES

| Phase | Check |
|---|---|
| 0 | Pre-test: report exists at correct full path, naming correct, PROJECT_STATE fresh, no phase* folders |
| 1 | Functional testing per module |
| 2 | System pipeline end-to-end |
| 3 | Failure mode simulation (API fail, WS disconnect, stale data, dedup, partial fill) |
| 4 | Async safety (race conditions, state corruption) |
| 5 | Risk rules enforced in code |
| 6 | Latency: ingest <100ms / signal <200ms / exec <500ms |
| 7 | Infra + Telegram (env-dependent) |

Stability score:
Architecture 20% / Functional 20% / Failure modes 20% / Risk 20% / Infra+Telegram 10% / Latency 10%

Verdict: APPROVED (≥85, zero critical) / CONDITIONAL (60–84) / BLOCKED (any critical or <60)

Environment:
- `dev` → infra/telegram: warn only, risk: enforced
- `staging` / `prod` → everything enforced

---

## COPILOT PR REVIEW — BLOCKING CONDITIONS

Any single one = immediate 🚫 BLOCKED:

| Code | Condition |
|---|---|
| B1 | FORGE-X report missing from `projects/polymarket/polyquantbot/reports/forge/` |
| B2 | Report naming format incorrect |
| B3 | Report missing any of 6 mandatory sections |
| B4 | `PROJECT_STATE.md` not updated in PR |
| B5 | Any `phase*/` folder present |
| B6 | File outside 11 domain folders |
| B7 | Hardcoded secret / API key |
| B8 | Full Kelly (α=1.0) used |
| B9 | RISK layer bypassed before EXECUTION |
| B10 | Bare `except: pass` or silent exception |
| B11 | `import threading` present |
| B12 | Execution guard (`ENABLE_LIVE_TRADING`) bypassed |

---

## RISK RULES (FIXED — never change in any task or report)

| Rule | Value |
|---|---|
| Kelly α | 0.25 — fractional only. Full Kelly FORBIDDEN. |
| Max position | ≤ 10% bankroll |
| Max concurrent | 5 trades |
| Daily loss | −$2,000 → pause all |
| Drawdown | 8% → block all |
| Liquidity min | $10,000 orderbook depth |
| Dedup | Required every order |
| Kill switch | Highest priority, Telegram-accessible |
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
| Database | PostgreSQL + Redis + InfluxDB |
| Secrets | .env only — never hardcoded |
| Operations | Idempotent — safe to retry |
| Resilience | Retry + timeout on all external calls |
| Logging | structlog — structured JSON |
| Errors | Zero silent failures |
| Pipeline | timeout + retry + dedup + DLQ |

---

## INTELLIGENCE LAYER

- News sentiment + drift detection
- Bayesian probability updates
- External API: `narrative.agent.heisenberg.so`

---

## BRIEFER — TEMPLATE SELECTION

| Report Type | Audience | Template |
|---|---|---|
| Internal: phase completion, validation, health, bug, backtest | Team | `TPL_INTERACTIVE_REPORT.html` |
| Client: progress, sprint delivery, go-live readiness | Client | `TPL_INTERACTIVE_REPORT.html` |
| Investor: phase update, performance | Investor | `TPL_INTERACTIVE_REPORT.html` |
| Investor: capital deployment, risk transparency | Investor | `REPORT_TEMPLATE_MASTER.html` |
| Any — print / PDF | Any | `REPORT_TEMPLATE_MASTER.html` |

Decision rule:
- Browser / device → `TPL_INTERACTIVE_REPORT.html` (default)
- Print / PDF / formal document → `REPORT_TEMPLATE_MASTER.html`
- Not specified → default interactive

---

## BRIEFER — TPL_INTERACTIVE (browser/device)

Structure: boot animation + tab navigation
Use `TAB STRUCTURE` in task:
```
TAB STRUCTURE:
- 01_[LABEL] → [content]
- 02_[LABEL] → [content]
- 03_[LABEL] → [content]
- 04_[LABEL] → [content]
```

Placeholders:

| Placeholder | Replace With |
|---|---|
| `{{REPORT_TITLE}}` | e.g. `Investor Update Phase 23.1` |
| `{{REPORT_CODENAME}}` | e.g. `Phase 23.1` |
| `{{REPORT_FOCUS}}` | e.g. `UI V3 Paper Activation` |
| `{{SYSTEM_NAME}}` | `PolyQuantBot` |
| `{{OWNER}}` | `Bayue Walker` |
| `{{REPORT_DATE}}` | e.g. `April 2026` |
| `{{SYSTEM_STATUS}}` | e.g. `PAPER_ACTIVE` |
| `{{BADGE_1_LABEL}}` | e.g. `Confidential` |
| `{{BADGE_2_LABEL}}` | e.g. `Paper Trading` |
| `{{TAB_1_LABEL}}` … `{{TAB_4_LABEL}}` | e.g. `OVERVIEW` |
| `{{TAB_1_HEADING}}` | e.g. `Executive Summary` |
| `{{NOTICE_TEXT}}` | Disclaimer text |
| `{{M1_LABEL}}` … `{{M8_LABEL}}` | Metric labels |
| `{{M1_VALUE}}` … `{{M8_VALUE}}` | Metric values |
| `{{M1_NOTE}}` … `{{M8_NOTE}}` | Metric notes |
| `{{PROG_1_LABEL}}` / `{{PROG_1_PCT}}` | Progress bar (% number only) |
| `{{LIST_1_LABEL}}` / `{{LIST_1_VALUE}}` | Data list rows |
| `{{S1_PHASE}}` / `{{S1_MODULE}}` / `{{S1_VERDICT}}` | SENTINEL table |
| `{{LIMIT_1_TITLE}}` / `{{LIMIT_1_DESC}}` | Known limitations |
| `{{FOOTER_DISCLAIMER}}` | Footer text |

Component classes:
- Metric cards: `success` / `warn` / `accent` / `danger` / `muted` / `info`
- Badges: `badge-accent` / `badge-warn` / `badge-success` / `badge-danger` / `badge-muted`
- Pipeline: `pipe-active` / `pipe-success` / `pipe-warn` / `pipe-inactive`
- Notice: `notice-warn` / `notice-success` / `notice-info` / `notice-danger`
- Checklist: default ✓ / `.warn` ! / `.error` ✗ / `.next` › / `.info` ·
- File tags: `tag-new` / `tag-mod` / `tag-del`
- SENTINEL verdict: `td-success` / `td-warn` / `td-danger`

---

## BRIEFER — REPORT_TEMPLATE_MASTER (PDF/print)

Structure: static scroll, `<section class="card">` blocks
Use `SECTION STRUCTURE` in task:
```
SECTION STRUCTURE:
(use <section class="card"> blocks)
- 01 — [TITLE] → [content]
- 02 — [TITLE] → [content]
- 03 — [TITLE] → [content]
- 04 — [TITLE] → [content]
```

PDF rules BRIEFER must follow:
- No overflow, no fixed heights, no animations
- Print-safe layout
- Include disclaimer if paper trading context

KV box classes: `positive` / `neutral` / `negative` / `info`
Pill classes: `pill-green` / `pill-orange` / `pill-red` / `pill-blue`
Milestone dots: `dot-done` / `dot-active` / `dot-pending` / `dot-future`
Risk cards: default amber / `.red` / `.green`

---

## BRIEFER — RISK CONTROLS TABLE (FIXED — never change)

| Rule | Value |
|---|---|
| Kelly Fraction (α) | 0.25 — fractional only |
| Max Position Size | ≤ 10% of total capital |
| Daily Loss Limit | −$2,000 hard stop |
| Drawdown Circuit-Breaker | > 8% → auto-halt |
| Signal Deduplication | Per (market, side, price, size) |
| Kill Switch | Telegram-accessible, immediate halt |

Only add phase-specific rows below these fixed rows.

---

## BUILD ROADMAP

```
Phase 1 — Foundation  : setup, repo, connections, infra
Phase 2 — Strategy    : signals, sizing, backtest
Phase 3 — Intelligence: engine, risk, scanner
Phase 4 — Production  : deploy, dashboard, confirm
```

---

## FRONTEND STACK (BRIEFER default)

Vite + React 18 + TypeScript + Tailwind CSS + Recharts + Zustand
Only use if COMMANDER specifies: Next.js / Chart.js / D3 / TradingView Lightweight Charts
