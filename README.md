<div align="center">

```
██╗    ██╗ █████╗ ██╗     ██╗  ██╗███████╗██████╗
██║    ██║██╔══██╗██║     ██║ ██╔╝██╔════╝██╔══██╗
██║ █╗ ██║███████║██║     █████╔╝ █████╗  ██████╔╝
██║███╗██║██╔══██║██║     ██╔═██╗ ██╔══██╗██╔══██╗
╚███╔███╔╝██║  ██║███████╗██║  ██╗███████╗██║  ██║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
           AI  D E V T R A D E  T E A M
```

**Multi-Agent AI Build System**

*Polymarket · TradingView · MT4/MT5 · Kalshi*

---

![Status](https://img.shields.io/badge/Status-Paper%20Beta%20Public--Ready-blue?style=for-the-badge)
![Execution](https://img.shields.io/badge/Execution-Paper%20Only-orange?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Private](https://img.shields.io/badge/Repo-Private-red?style=for-the-badge&logo=github)

</div>

---

# Walker AI DevTrade Team

> _Operational Workflow & Execution Model_

---

## 🚀 Overview

Walker AI DevTrade Team orchestrates AI-powered trading development with a disciplined, truth-centric approach. Our workflow ensures rapid delivery without compromising correctness or safety.

**Core flow:**

- **Mr. Walker** sets direction  
- **COMMANDER** interprets repo truth, scopes work, resolves minor issues independently  
- **NEXUS** (FORGE-X, SENTINEL, BRIEFER) executes assigned tasks  
- **COMMANDER** reviews, decides, and merges/close PRs autonomously  

> _Principles: Tasks flow top-down, scope is controlled, repo truth is the single source of reality, and minor issues don’t disturb Mr. Walker._

---

## 🗂️ Repo Structure

```plaintext
walker-ai-team/
├── AGENTS.md                 # Global rules & authority
├── PROJECT_REGISTRY.md       # Project list & active status
├── docs/                    # Knowledge, blueprints, templates
│   ├── COMMANDER.md           # COMMANDER reference guide
│   └── blueprint/             # System architecture guidance
├── lib/                     # Shared cross-project libraries
└── projects/                # Multi-project workspace
    ├── polymarket/
    │   └── polyquantbot/     # ACTIVE PROJECT_ROOT
    │       ├── state/
    │       │   ├── PROJECT_STATE.md
    │       │   ├── ROADMAP.md
    │       │   └── work_checklist.md
    │       ├── core/
    │       ├── ... (domain folders)
    │       └── reports/
    │           ├── forge/
    │           ├── sentinel/
    │           ├── briefer/
    │           └── archive/
```
Each project follows strict domain folder structure enforced by global rules.

## 🎭 Roles & Responsibilities
Role

Description

Mr. Walker

Owner & final decision maker — sets direction, intervenes only on major decisions

COMMANDER

Architect, gatekeeper, orchestrator — reads repo truth, merges lanes, routes tasks, fixes minor issues, auto merges

NEXUS

Multi-agent execution team: FORGE-X (builder), SENTINEL (validator), BRIEFER (reporter)

## ⚙️ Operating Modes
Mode

Description

Normal

Default; comprehensive review & validation for uncertain or complex tasks

Degen

Explicitly triggered fast execution mode for clear, low-risk lanes; batches fixes, reduces noise

Degen mode respects all repo truth and safety checks — no bypass or overclaim allowed.

## 🔄 Workflow Highlights
Task Issuance: Mr. Walker provides direction
Interpretation: COMMANDER reads repo truth and sets execution lanes
Execution: NEXUS agents carry out tasks in scoped domains
Review: COMMANDER inspects outputs, resolves minor fixes autonomously
Merge: COMMANDER auto-approves and merges cleaned PRs
Sync: Update project state, roadmap, and checklists accordingly

## 📊 GitHub Practices
Branching: Always use feature/{feature} format
Commits: Bundle code, reports, and updated state files in PRs
Bots: Advisory only; COMMANDER triages their comments as blockers or minor fixes
Merging: COMMANDER holds merge autonomy; NEXUS merges only when instructed

## ⚠️ Drift & Noise Management
Drift (state inconsistencies, report/code mismatches) halts progress until resolved
Noise (cosmetic debates, micro-task fragmentation) minimized via degen mode and compact communication
Consistent synchronization of PROJECT_STATE.md, ROADMAP.md, and work_checklist.md is imperative


## 💡 Efficiency & Cost Discipline
COMMANDER communicates concisely by default
Bulk multiple minor fixes per batch to reduce overhead
Generate brief handoffs near session limits for smooth context transition
Enforce explicit project tagging in multi-project scenarios
Prefer degen mode for cost-effective throughput without sacrificing accuracy

## 📬 Contact & Contribution
Please refer to AGENTS.md and COMMANDER.md for detailed guidelines and contribution protocols.

© 2025 Walker AI DevTrade Team
Built for speed, safety, and scalability in AI-driven trading.
