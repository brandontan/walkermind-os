## Walker AI DevTrade Team 
### Operational Workflow and Execution Model
#### Document type: Internal operational reference Authority: Supporting document — AGENTS.md is the authoritative rule source Version: 1.0 | Last Updated: 2025-07-11

## 1. Big Picture

Mr. Walker sets direction
→ COMMANDER reads repo truth, determines lane, resolves minor issues independently
→ NEXUS executes via the appropriate role (FORGE-X / SENTINEL / BRIEFER)
→ returns to COMMANDER for review and decision
→ COMMANDER auto merges / closes / routes next lane

Principles:

Tasks come from COMMANDER
Scope stays controlled
Repo truth = center of all decisions
Code truth wins over report wording
Minor issues = COMMANDER handles directly, don't bother Mr. Walker


## 2. Repo Structure
### 2.1 Tree
```text
walker-ai-team/
├── AGENTS.md                          ← highest authority (global rules)
├── PROJECT_REGISTRY.md                ← project list + active status
├── docs/
│   ├── CLAUDE.md                      ← rules for Claude Code agent
│   ├── KNOWLEDGE_BASE.md             ← architecture, infra, API reference
│   ├── COMMANDER.md                   ← COMMANDER operating reference
│   ├── blueprint/
│   │   └── crusaderbot_final_decisions.md
│   └── templates/
│       ├── PROJECT_STATE_TEMPLATE.md
│       ├── ROADMAP_TEMPLATE.md
│       ├── TPL_INTERACTIVE_REPORT.html
│       └── REPORT_TEMPLATE_MASTER.html
├── lib/                               ← shared libraries across projects
└── projects/
    ├── polymarket/
    │   └── polyquantbot/              ← PROJECT_ROOT (active)
    │       ├── state/
    │       │   ├── PROJECT_STATE.md
    │       │   ├── ROADMAP.md
    │       │   └── work_checklist.md
    │       ├── core/
    │       ├── data/
    │       ├── strategy/
    │       ├── intelligence/
    │       ├── risk/
    │       ├── execution/
    │       ├── monitoring/
    │       ├── api/
    │       ├── infra/
    │       ├── backtest/
    │       └── reports/
    │           ├── forge/
    │           ├── sentinel/
    │           ├── briefer/
    │           └── archive/
    ├── tradingview/
    │   ├── indicators/
    │   └── strategies/
    └── mt5/
        ├── ea/
        └── indicators/
```

2.2 Layer Functions
Root repo — Global governance

AGENTS.md = highest authority, applies across all projects
PROJECT_REGISTRY.md = project list + active status
These are the system's decision center. Not supplementary files.

PROJECT_REGISTRY.md — Project navigation

Single file that tells which projects exist, where they live, and which are active. Agent reads this → immediately knows where to work.

Rules:

1 active project → NEXUS defaults to it, no tag needed
Multi-project active → every task must tag the project
No tag + multi-project → NEXUS asks, never assumes
docs/ — Knowledge, reference, blueprint, templates

COMMANDER.md = COMMANDER operating reference
CLAUDE.md = rules for Claude Code agent
KNOWLEDGE_BASE.md = architecture, infra, API, conventions reference
blueprint/ = target architecture / system-shape guidance
templates/ = templates for state, roadmap, and reports
Blueprint is a target architecture reference — not current truth. When blueprint and code differ, code defines current reality, blueprint defines the direction.

lib/ — Shared libraries

Shared libraries and utilities across projects.

projects/ — Multi-project workspace

Repo is designed for multiple workstreams. Each project has its own structure under projects/. Which project is active is determined by PROJECT_REGISTRY.md.

state/ — Project operational truth

Each project has its own state/ folder under PROJECT_ROOT:

PROJECT_STATE.md — current operational condition
ROADMAP.md — phase / milestone truth
work_checklist.md — granular task tracking
These three files must always stay in sync. If one says done but the others haven't been updated, that's drift.

Domain structure enforcement

Inside the active PROJECT_ROOT, folder structure follows the domain structure enforced by AGENTS.md: core/, data/, strategy/, intelligence/, risk/, execution/, monitoring/, api/, infra/, backtest/, and reports/. No phase*/ folders or legacy structure allowed.

reports/ — Evidence trail

Each project has its own reports/ folder under PROJECT_ROOT:

forge/ — build reports from FORGE-X
sentinel/ — validation reports from SENTINEL
briefer/ — communication artifacts from BRIEFER
archive/ — reports older than 7 days moved here
Reports are the evidence trail used by COMMANDER for review, SENTINEL for validation, and BRIEFER for transformation.

---

## 3. Who Does What
Mr. Walker
Role: Owner / Final Decision-Maker

Ultimate authority. Sets direction, priorities, and makes final calls. Mr. Walker should only be involved in decisions that genuinely require owner authority — not minor issues.

COMMANDER
Role: Systems Architect / Gatekeeper / Orchestrator

COMMANDER operates in direct chat with Mr. Walker — this is where decisions, reviews, and steering happen. Functions:

Read repo truth
Identify active lanes
Merge adjacent work when safe
Route tasks to FORGE-X, SENTINEL, or BRIEFER
Review outputs
Auto merge / close PRs by own decision
Fix minor bugs, small errors, cosmetic issues directly — no escalation
Escalate to Mr. Walker only for: large scope, risk, capital, safety, or decisions requiring owner authority.

NEXUS
Role: Multi-Agent Specialist Team

NEXUS is the execution team consisting of three specialist agents: FORGE-X, SENTINEL, and BRIEFER. Each has different capabilities and responsibilities. NEXUS works under COMMANDER direction — receives scoped tasks, executes according to each role's expertise, and returns output for review.

NEXUS executes in separate environments: Claude Code, Codex, or other tools as needed. NEXUS does not merge / close PRs independently — only executes when COMMANDER instructs.

FORGE-X
Role: Builder / Implementer / Refactor / Fix Specialist

Implement, patch, refactor, fix, update state/report, open PR.

SENTINEL
Role: Validator / Auditor / Safety Enforcer

Validate, audit, test, enforce safety. Only active for MAJOR tasks or when COMMANDER explicitly requests audit.

BRIEFER
Role: Reporter / Visualizer / Communication Layer

HTML reports, prompt artifacts, visual summaries, UI/report transforms. Only works from validated data. Runs after required validation path is satisfied.

---

## 4. Operating Modes
Normal Mode (Default)
Always active unless Mr. Walker explicitly triggers degen mode.

Used for: reviews, task generation, sync, validation, work where scope isn't 100% clear yet.

Degen Mode (Explicit Trigger Only)
Only active when Mr. Walker triggers it explicitly. COMMANDER must not self-activate.

Why it exists:

Degen mode exists to reduce wasted time from recurring drift and review noise while keeping repo-truth and safety gates intact.

What degen mode does:

Prioritizes implementation over repeated discussion
Batches small safe fixes into one pass
Skips cosmetic / non-functional noise unless explicitly requested
Reduces micro-task fragmentation
Minimizes back-and-forth
Keeps pushing until lane is closed or one real blocker remains
What degen mode does NOT do:

What degen mode does NOT do:

Override AGENTS.md
Ignore repo truth
Allow overclaiming
Bypass safety, validation, or runtime-integrity gates
Excuse drift
Deactivation: Lane complete, or Mr. Walker says stop / normal / reset.

## 5. Repo Truth — Foundation Before Work
Priority

Source

Function

1

AGENTS.md

Highest authority

2

PROJECT_REGISTRY.md

Project navigation

3

{PROJECT_ROOT}/state/PROJECT_STATE.md

Operational truth

4

{PROJECT_ROOT}/state/ROADMAP.md

Milestone truth

5

{PROJECT_ROOT}/state/work_checklist.md

Granular task tracking

6

Reports (reports/forge/, reports/sentinel/)

Supporting evidence

---

## 6. Normal Workflow
Step A — Mr. Walker sets direction
Step B — COMMANDER reads repo truth
Checks: PROJECT_REGISTRY.md → active project → state/ files → active lane → blockers → tier → claim level.

Step C — COMMANDER forms execution lane
Adjacent open items in the same family → merge into one lane. Prefer lane closure over fragmented progress.

Step D — Task routed to the right role

Tier

Flow

MINOR

COMMANDER → FORGE-X → COMMANDER (auto merge)

STANDARD

COMMANDER → FORGE-X → COMMANDER (review + merge)

MAJOR

COMMANDER → FORGE-X → SENTINEL → COMMANDER (validate + merge)

BRIEFER

Runs after required validation path is satisfied

Minor bug / error / cosmetic → COMMANDER fixes directly, skips task creation.

Step E — FORGE-X implements
Required: work within scope, verify actual branch, update forge report + state files, commit and open PR.

---

## 7. GitHub Workflow
7.1 Branch

Format: feature/{feature}

Applies to all environments. Branch reference must be exact actual branch / exact PR head — never from memory or task title.

7.2 Commit + Report + State
PR must carry a complete package: code + forge report + state files update.

7.3 Pull Request
PR contains: motivation, testing, report path, state updates, claim/tier context.

COMMANDER reviews: files changed, bot comments, report, branch traceability, state drift, claim vs actual code.

7.4 Bot Reviews
Auto PR review bots = optional support only.

COMMANDER classifies:

Classification

Action

BLOCKER

Hold merge

MINOR SAFE FIX

Resolve quickly

IGNORE / NON-ACTIONABLE

Don't stall PR

7.5 Merge / Hold / Close
COMMANDER auto merges / closes by own decision. NEXUS does not merge independently.

After merge: verify result → sync state files → determine next lane.

---

## 8. Drift & Noise
8.1 Drift

Drift = repo truth out of sync.

Branch traceability drift — PR head and written references don't match
State / roadmap / checklist drift — PROJECT_STATE.md, ROADMAP.md, work_checklist.md say different things
Report / code drift — report claims complete, actual code is narrower
Claim drift / overclaim — wording implies readiness that repo truth doesn't support
Surface-boundary drift — public/operator/admin paths get mixed
Blueprint / implementation drift — target architecture treated as current truth
Phase / lane drift — lane marked complete too early or still shown active after closure
Encoding / artifact drift — mojibake, bad formatting, invalid artifact structure
8.2 Noise
Noise = small friction with no material improvement.

Cosmetic wording debates — tiny style issues with no behavior impact
Micro-task fragmentation — one fix becomes multiple tiny tasks
Explanation loops — repeating context without implementing
Review-nit inflation — minor comments treated as blockers
Redundant review churn — evidence is clear but ceremonial re-checking continues
Scope creep disguised as cleanup — small tasks expand into broad rewrites
User-overhead drag — too many decisions pushed to user for obvious low-risk items
8.3 Impact
Drift + noise = lane drag, over-review, branch confusion, delayed closure.

---

9. Cost Discipline
