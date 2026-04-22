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
# Walker AI DevTrade Team — Operational Workflow and Execution Model

> **Document type:** Internal operational reference  
> **Authority:** Supporting document — `AGENTS.md` is the authoritative rule source  
> **Version:** 1.0 | Last Updated: 2025-07-11

---

## 1. Big Picture

Mr. Walker sets direction  
→ COMMANDER reads repo truth, determines lane, resolves minor issues independently  
→ NEXUS executes via the appropriate role (FORGE-X / SENTINEL / BRIEFER)  
→ returns to COMMANDER for review and decision  
→ COMMANDER auto merges / closes / routes next lane

Principles:

- Tasks come from COMMANDER  
- Scope stays controlled  
- Repo truth = center of all decisions  
- Code truth wins over report wording  
- Minor issues = COMMANDER handles directly, do not bother Mr. Walker  

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


### 2.2 Layer Functions

**Root repo — Global governance**

- `AGENTS.md` = highest authority, applies across all projects  
- `PROJECT_REGISTRY.md` = project list + active status  

These are the system's decision center. Not supplementary files.

**PROJECT_REGISTRY.md — Project navigation**

Single file that tells which projects exist, where they live, and which are active. Agents read this → immediately knows where to work.

Rules:  
- 1 active project → NEXUS defaults to it, no tag needed  
- Multi-project active → every task must tag the project  
- No tag + multi-project → NEXUS asks, never assumes  

**docs/ — Knowledge, reference, blueprint, templates**

- `COMMANDER.md` = COMMANDER operating reference  
- `CLAUDE.md` = rules for Claude Code agent  
- `KNOWLEDGE_BASE.md` = architecture, infra, API, conventions reference  
- `blueprint/` = target architecture / system-shape guidance  
- `templates/` = templates for state, roadmap, and reports  

Blueprint is a target architecture reference — not current truth. When blueprint and code differ, code defines current reality, blueprint defines the direction.

**lib/ — Shared libraries**

Shared libraries and utilities across projects.

**projects/ — Multi-project workspace**

Each project has its own structure under `projects/`. Which project is active is determined by `PROJECT_REGISTRY.md`.

**state/ — Project operational truth**

Each project has a `state/` folder under PROJECT_ROOT containing:

- `PROJECT_STATE.md` — current operational condition  
- `ROADMAP.md` — phase / milestone truth  
- `work_checklist.md` — granular task tracking  

These files must always stay in sync. Discrepancies constitute drift.

**Domain structure enforcement**

Active PROJECT_ROOT follows domain folder structure enforced by `AGENTS.md`:  
`core/`, `data/`, `strategy/`, `intelligence/`, `risk/`, `execution/`, `monitoring/`, `api/`, `infra/`, `backtest/`, and `reports/`.  
No legacy or arbitrary folders allowed.

**reports/ — Evidence trail**

Contains:  
- `forge/` (FORGE-X build reports)  
- `sentinel/` (SENTINEL validation reports)  
- `briefer/` (BRIEFER communication artifacts)  
- `archive/` (reports >7 days archived)  

---

## 3. Who Does What

### Mr. Walker

Owner / final decision maker; only involved on major or high-risk decisions.

### COMMANDER

Architect, gatekeeper, orchestrator interfacing directly with Mr. Walker.  

Responsibilities:

- Read repo truth  
- Identify active lanes  
- Merge adjacent work when safe  
- Route tasks to FORGE-X, SENTINEL, BRIEFER  
- Review work  
- Auto merge / close PRs  
- Fix minor bugs and cosmetic issues without escalation  

Escalates only scope/risk/safety/capital decisions to Mr. Walker.

### NEXUS

Multi-agent execution team comprising FORGE-X (builder), SENTINEL (validator), BRIEFER (reporter) executing scoped tasks under COMMANDER's supervision.

### FORGE-X

Build, patch, refactor, fix, update state and reports, open PRs.

### SENTINEL

Validate and audit major changes or upon explicit command.

### BRIEFER

Produce reports and visual summaries from validated data post-validation.

---

## 4. Operating Modes

### Normal Mode (default)

Always active unless overridden explicitly. Used for complex or unclear scope.

### Degen Mode (explicit trigger only)

Activated only by explicit command from Mr. Walker. Speeds execution on clear, low-risk lanes.

---

## 5. Repo Truth — Foundations

Priority list of files establishing system “truth”:

1. `AGENTS.md` (highest authority)  
2. `PROJECT_REGISTRY.md` (project and status registry)  
3. `{PROJECT_ROOT}/state/PROJECT_STATE.md` (operational state)  
4. `{PROJECT_ROOT}/state/ROADMAP.md` (milestones)  
5. `{PROJECT_ROOT}/state/work_checklist.md` (task tracking)  
6. Reports in `reports/` folders (evidence trails)  

---

## 6. Normal Workflow

Steps:

- Mr. Walker issues task/direction  
- COMMANDER reads truth files, analyzes lanes, blockers, tiers/claims  
- COMMANDER merges related items into lane  
- Tasks assigned per tier and routed to correct agents  
- FORGE-X implements within scope and opens PR  
- Minor fixes handled directly by COMMANDER

---

## 7. GitHub Workflow

- Branch naming convention: `feature/{feature}`  
- PRs contain code + reports + updated state files  
- COMMANDER reviews code, bots, reports, branch correctness, claims  
- Bots are advisory, COMMANDER triages comments accordingly  
- COMMANDER auto merges or closes PRs; NEXUS only executes on command  
- Post-merge sync state files and plan next lane  

---

## 8. Drift & Noise

Drift = repo truth inconsistencies with patterns like branch mismatches, unsynced state/roadmap/checklists, report/code divergences, overclaims, mixed surface boundaries, blueprint vs code inconsistencies, premature lane closure, malformed artifacts.

Noise = wasteful minor frictions like cosmetic debates, micro-task fragmentation, repeated explanations, nitpicks, redundant re-checks, scope creep disguised as cleanup, excessive user overhead.

Their combined effect decreases delivery speed and increases confusion.

---

## 9. Cost Discipline

- COMMANDER outputs are compact by default; detailed only on request  
- Batch multiple minor fixes to reduce overhead  
- Minimize explanation loops  
- Tasks to NEXUS are concise, focused, with references; avoid duplicating repo content  
- COMMANDER resolves minor issues independently to cut communication rounds  
- Prefer degen mode for cost-effective throughput without sacrificing accuracy  
- Generate brief handoffs near session limits using a standard 5-line format  

---

## 10. Key Lessons

- Delivery speed is hindered more by drift and noise than coding difficulty  
- Strict GitHub workflow adherence ensures trustworthy repo truth  
- Consistent synchronization of state, roadmap, checklist, and reports is crucial  
- Fast execution modes remain subject to authoritative rules and safety  
- Minor fixes must not escalate to owner; COMMANDER is empowered to resolve  
- Efficient token usage maximizes AI-assisted delivery

---

*End of document.*
