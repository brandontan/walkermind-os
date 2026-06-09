<div align="center">

# WalkerMind OS

**Intelligent by design. Autonomous by nature.**

*Powered by W.A.R.P Engine — Walker Autonomous Routing Protocol*

---

![Status](https://img.shields.io/badge/Status-Paper%20Beta-blue?style=for-the-badge)
![Execution](https://img.shields.io/badge/Execution-Paper%20Only-orange?style=for-the-badge)
![Engineering](https://img.shields.io/badge/Engineering-Live%20Ready-success?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Private](https://img.shields.io/badge/Repo-Private-red?style=for-the-badge&logo=github)
![Engine](https://img.shields.io/badge/Engine-W.A.R.P-7c3aed?style=for-the-badge)

</div>

---

## Overview

**WalkerMind OS** is a multi-agent autonomous trading infrastructure powered by the **W.A.R.P Engine** — a structured execution protocol for building, validating, and operating algorithmic systems across prediction markets and financial platforms.

The system operates under a strict authority chain. WARP🔹CMD orchestrates. WARP🔸CORE executes. Repo-truth governance and safety gates are enforced at every tier.

**Active project:** `projects/polymarket/crusaderbot` — CrusaderBot on Polymarket.

*Polymarket · Kalshi · TradingView · MT4/MT5*

---

## Operating Posture

**Production:** PAPER ONLY. All five LIVE activation guards — `ENABLE_LIVE_TRADING`,
`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`,
`SECURITY_HARDENING_VALIDATED` — default `false` and are forced `false` in
`fly.toml`. New users land on `trading_mode='paper'` by **both** schema column
default **and** explicit `INSERT`; a LIVE flip requires an 8-gate checklist
plus typed `CONFIRM`.

**Engineering:** LIVE-ready. On-chain capital paths (withdraw, deposit sweep,
gasless-Safe custody) are merged, SENTINEL-approved, and triple-gated OFF. No
remaining `NotImplementedError` in the trading/risk/execution/redeem/withdraw/sweep
paths. Remaining work to go live is owner-operational (fund master wallet,
flip guards in the documented order). See
[`projects/polymarket/crusaderbot/state/LIVE_READINESS.md`](projects/polymarket/crusaderbot/state/LIVE_READINESS.md).

---

## System Architecture

```
WalkerMind OS
│
├── WARP🔹CMD           Director — reads repo truth, routes tasks, gates merges
└── WARP🔸CORE          Execution Team
    ├── WARP•FORGE       Build — implements, patches, refactors, opens PRs
    ├── WARP•SENTINEL    Review — audits MAJOR changes before merge
    ├── WARP•ECHO        Report — produces HTML reports and communication artifacts
    └── WARP•R00T        Architect — root-cause investigation + system hardening
                          (assigned explicitly; otherwise FORGE is the default)
```

---

## Authority Chain

```
Mr. Walker  →  WARP🔹CMD  →  WARP🔸CORE (WARP•FORGE / WARP•SENTINEL / WARP•ECHO)
```

| Agent | Role |
|---|---|
| **Mr. Walker** | Owner. Final authority on scope, risk, and capital decisions. |
| **WARP🔹CMD** | Architect and gatekeeper. Reads repo truth, routes tasks, reviews and merges PRs. |
| **WARP•FORGE** | Builder. Implements, patches, refactors, opens PRs. |
| **WARP•SENTINEL** | Validator. Audits MAJOR changes before merge. |
| **WARP•ECHO** | Reporter. Produces HTML reports and communication artifacts from validated data. |
| **WARP•R00T** | System architect / hardening authority. Assigned explicitly for root-cause work, audits, and system-wide reliability passes. |

---

## Repo Structure

```
walkermind-os/
├── AGENTS.md                           ← highest authority — global rules
├── PROJECT_REGISTRY.md                 ← active project registry
├── CLAUDE.md                           ← Claude Code agent rules
├── COMMANDER.md                        ← WARP🔹CMD operating reference
├── docs/
│   ├── KNOWLEDGE_BASE.md               ← architecture, infra, API reference
│   ├── workflow_and_execution_model.md ← W.A.R.P operational protocol
│   ├── blueprint/                      ← target architecture guidance
│   └── templates/                      ← state, roadmap, and report templates
├── lib/                                ← shared libraries across projects
└── projects/
    ├── polymarket/
    │   └── crusaderbot/               ← PROJECT_ROOT (active)
    │       ├── state/
    │       │   ├── PROJECT_STATE.md    ← operational truth
    │       │   ├── ROADMAP.md          ← milestone truth
    │       │   ├── WORKTODO.md         ← task tracking
    │       │   └── CHANGELOG.md        ← lane closure history
    │       ├── core/ · data/ · strategy/ · intelligence/
    │       ├── risk/ · execution/ · monitoring/
    │       ├── api/ · infra/ · backtest/
    │       └── reports/
    │           ├── forge/              ← WARP•FORGE build reports
    │           ├── sentinel/           ← WARP•SENTINEL validation reports
    │           ├── briefer/            ← WARP•ECHO communication artifacts
    │           └── archive/            ← reports older than 7 days
    ├── tradingview/
    │   ├── indicators/
    │   └── strategies/
    └── mt5/
        ├── ea/
        └── indicators/
```

---

## Source of Truth — Priority Order

| # | File | Role |
|---|---|---|
| 1 | `AGENTS.md` | Highest authority — overrides everything |
| 2 | `PROJECT_REGISTRY.md` | Active project navigation |
| 3 | `{PROJECT_ROOT}/state/PROJECT_STATE.md` | Current operational state |
| 4 | `{PROJECT_ROOT}/state/ROADMAP.md` | Phase and milestone truth |
| 5 | `{PROJECT_ROOT}/state/WORKTODO.md` | Granular task tracking |
| 6 | `reports/forge/`, `reports/sentinel/` | Build and validation evidence |

When sources conflict: `AGENTS.md` wins. Code truth wins over report wording.

---

## Validation Tiers

| Tier | Scope | Gate |
|---|---|---|
| **MINOR** | Wording, docs, templates, non-runtime cleanup | WARP🔹CMD review |
| **STANDARD** | User-facing runtime behavior outside trading core | WARP🔹CMD review |
| **MAJOR** | Execution, risk, capital, async core, pipeline, live-trading | WARP•SENTINEL required before merge |

---

## Branch Naming

```
WARP/{feature}            ← FORGE / SENTINEL / ECHO lanes
WARP/ROOT/{feature}       ← WARP•R00T lanes
```

Short hyphen-separated slug. No dots, underscores, or date suffixes. Auto-generated
`claude/*` branches are **forbidden** — every branch must be pre-declared.

```
WARP/wallet-state-read-boundary       ✓
WARP/ROOT/paper-default-hardening     ✓
WARP/implement_wallet_state           ✗  (underscores)
WARP/phase6.5.3-fix-2026-04-16        ✗  (dots, date)
claude/happy-tesla-30Qei              ✗  (auto-generated)
```

---

## Risk Constants

These values are fixed. No code or report may deviate.

| Rule | Value |
|---|---|
| Kelly fraction (α) | `0.25` — fractional only; `1.0` is forbidden |
| Max position size | `≤ 10%` of total capital |
| Max concurrent trades | `5` |
| Daily loss limit | `−$2,000` hard stop |
| Max drawdown | `> 8%` → system halt |
| Liquidity minimum | `$10,000` orderbook depth |
| Signal deduplication | Mandatory |
| Kill switch | Mandatory and testable |

---

## W.A.R.P Operating Modes

| Mode | Activated By | Behavior |
|---|---|---|
| **Normal Mode** | Default | Repo-truth first, scope-tight execution, evidence-based review |
| **Degen Mode** | Mr. Walker only — `degen mode on` | Fast execution, batch minor fixes, minimum friction |

---

## Key References

| Document | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Master rules — read before every task |
| [`docs/workflow_and_execution_model.md`](docs/workflow_and_execution_model.md) | Full W.A.R.P operational protocol |
| [`docs/KNOWLEDGE_BASE.md`](docs/KNOWLEDGE_BASE.md) | Architecture, infra, API, and conventions |
| [`PROJECT_REGISTRY.md`](PROJECT_REGISTRY.md) | Active project list |

---

<div align="center">

**WalkerMind OS** · Powered by **W.A.R.P Engine**

*Walker Autonomous Routing Protocol · Bayue Walker · Private Repository*

</div>
