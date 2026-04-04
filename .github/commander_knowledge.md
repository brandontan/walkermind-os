## COMMANDER KNOWLEDGE FILE
- Attach as knowledge document in Custom GPT.

---

## INSTRUCTIONS FILE
- (commander_customgpt.md) always reads this first.

---

## REPO & PROJECT STRUCTURE

```
https://github.com/bayuewalker/walker-ai-team

projects/polymarket/polyquantbot/
projects/tradingview/indicators/
projects/tradingview/strategies/
projects/mt5/ea/
projects/mt5/indicators/
```

Reference docs:
- `PROJECT_STATE.md` — current phase, completed, next priority
- `docs/KNOWLEDGE_BASE.md` — Polymarket CLOB API, auth, order flow, WebSocket
- `docs/CLAUDE.md` — agent rules and context
- `docs/pico.pdf` — reference material
- `docs/advancee_trade_strategy.pdf` — advanced strategy reference

---

## DOMAIN STRUCTURE (11 folders — LOCKED)

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
| BRIEFER | `feature/briefer/[task-name]` | `feature/briefer/22-2-investor-report` |
| SENTINEL | uses same branch as FORGE-X task being validated | — |

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
| `22_2_investor_update.md` | `report.md` |
| `22_2_investor_update.html` | `structure_refactor.md` |

---

## FORGE-X REPORT — 6 MANDATORY SECTIONS

Every forge report must contain all 6:
1. What was built
2. Current system architecture
3. Files created / modified (full paths)
4. What is working
5. Known issues
6. What is next

---

## PROJECT_STATE.md — 5 UPDATABLE SECTIONS

FORGE-X updates ONLY these sections after every task:
- `STATUS`
- `COMPLETED`
- `IN PROGRESS`
- `NEXT PRIORITY`
- `KNOWN ISSUES`

Never rewrite other sections.

Commit message format: `"update: project state after [task name]"`

---

## SENTINEL — 8 VALIDATION PHASES

| Phase | Check |
|---|---|
| 0 | Pre-test: report exists, naming correct, PROJECT_STATE fresh, no phase* folders |
| 1 | Functional testing per module |
| 2 | System pipeline end-to-end |
| 3 | Failure mode simulation (API fail, WS disconnect, stale data, dedup, partial fill) |
| 4 | Async safety (race conditions, state corruption) |
| 5 | Risk rules enforced in code |
| 6 | Latency validation (ingest <100ms, signal <200ms, exec <500ms) |
| 7 | Infra + Telegram validation (env-dependent) |

Stability score:
- Architecture 20% / Functional 20% / Failure modes 20% / Risk 20% / Infra+Telegram 10% / Latency 10%

Verdict: APPROVED (≥85, zero critical) / CONDITIONAL (60–84) / BLOCKED (any critical or <60)

Environment rules:
- `dev` → infra/telegram: warn only, risk: enforced
- `staging` / `prod` → everything enforced

---

## COPILOT PR REVIEW — BLOCKING CONDITIONS

Any single one = immediate 🚫 BLOCKED:

| Code | Condition |
|---|---|
| B1 | FORGE-X report missing from `reports/forge/` |
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
Kelly    = (p·b − q) / b  →  always use 0.25f
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
| Pipeline | Every pipeline: timeout + retry + dedup + DLQ |

---

## INTELLIGENCE LAYER

- News sentiment + drift detection
- Bayesian probability updates
- External API: `narrative.agent.heisenberg.so`

---

## BRIEFER — TEMPLATE SELECTION

Decision rule:
- Dibuka di browser / device → `TPL_INTERACTIVE_REPORT.html` (default)
- Print / PDF / dokumen formal → `REPORT_TEMPLATE_MASTER.html`
- COMMANDER tidak specify → default ke interactive

| Report Type | Audience | Template |
|---|---|---|
| Internal: phase completion, validation, health, bug, backtest | Team | `TPL_INTERACTIVE_REPORT.html` |
| Client: progress, sprint delivery, go-live readiness | Client | `TPL_INTERACTIVE_REPORT.html` |
| Investor: phase update, performance | Investor | `TPL_INTERACTIVE_REPORT.html` |
| Investor: capital deployment, risk transparency | Investor | `REPORT_TEMPLATE_MASTER.html` |
| Any — print / PDF | Any | `REPORT_TEMPLATE_MASTER.html` |

Template locations in repo:
```
docs/templates/TPL_INTERACTIVE_REPORT.html   ← cross-device, boot animation, tabs
docs/templates/REPORT_TEMPLATE_MASTER.html   ← static scroll, PDF-optimized
```

---

## BRIEFER — PLACEHOLDER REFERENCE (TPL_INTERACTIVE)

| Placeholder | Replace With |
|---|---|
| `{{REPORT_TITLE}}` | e.g. `Investor Update Phase 22.2` |
| `{{REPORT_CODENAME}}` | e.g. `Phase 22.2` |
| `{{REPORT_FOCUS}}` | e.g. `Pre-Capital Validation Complete` |
| `{{SYSTEM_NAME}}` | `PolyQuantBot` |
| `{{OWNER}}` | `Bayue Walker` |
| `{{REPORT_DATE}}` | e.g. `April 2026` |
| `{{SYSTEM_STATUS}}` | e.g. `READY_FOR_CAPITAL` |
| `{{BADGE_1_LABEL}}` | e.g. `Confidential` |
| `{{BADGE_2_LABEL}}` | e.g. `Pre-Capital Phase` |
| `{{TAB_1_LABEL}}` … `{{TAB_4_LABEL}}` | Tab labels e.g. `OVERVIEW` |
| `{{TAB_1_HEADING}}` | e.g. `Executive Summary` |
| `{{NOTICE_TEXT}}` | Disclaimer text |
| `{{M1_LABEL}}` … `{{M8_LABEL}}` | Metric card labels |
| `{{M1_VALUE}}` … `{{M8_VALUE}}` | Metric card values |
| `{{M1_NOTE}}` … `{{M8_NOTE}}` | Metric card notes |
| `{{PROG_1_LABEL}}` / `{{PROG_1_PCT}}` | Progress bar label + % (number only) |
| `{{PROG_TOTAL_LABEL}}` / `{{PROG_TOTAL_VALUE}}` | Total row |
| `{{LIST_1_LABEL}}` / `{{LIST_1_VALUE}}` | Data list rows |
| `{{S1_PHASE}}` / `{{S1_MODULE}}` / `{{S1_VERDICT}}` | SENTINEL table rows |
| `{{LIMIT_1_TITLE}}` / `{{LIMIT_1_DESC}}` | Known limitations |
| `{{FOOTER_DISCLAIMER}}` | Footer disclaimer text |

---

## BRIEFER — COMPONENT CLASSES

**Metric cards** (border-left color):
`success` green / `warn` amber / `accent` cyan / `danger` red / `muted` gray / `info` blue

**Badges:**
`badge-accent` cyan / `badge-warn` amber / `badge-success` green / `badge-danger` red / `badge-muted` gray

**Pipeline nodes:**
`pipe-active` cyan / `pipe-success` green / `pipe-warn` amber / `pipe-inactive` gray

**Notice boxes:**
`notice-warn` amber / `notice-success` green / `notice-info` cyan / `notice-danger` red

**Checklist items:**
default ✓ green / `.warn` ! amber / `.error` ✗ red / `.next` › cyan / `.info` · gray

**File tags:**
`tag-new` green / `tag-mod` cyan / `tag-del` red

**SENTINEL table verdict classes:**
`td-success` / `td-warn` / `td-danger`

---

## BRIEFER — RISK CONTROLS TABLE (FIXED VALUES)

In every report, Risk Controls section uses these FIXED values — never change:

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

## FRONTEND STACK (built by BRIEFER)

Default: Vite + React 18 + TypeScript + Tailwind CSS + Recharts + Zustand
Use only if COMMANDER specifies: Next.js (SSR) / Chart.js / D3 / TradingView Lightweight Charts
