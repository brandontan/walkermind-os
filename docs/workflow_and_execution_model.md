# N.W.A.P — Operational Protocol & Execution Model

> **Document type:** Internal operational reference
> **Authority:** Supporting document — `AGENTS.md` is the authoritative rule source
> **Version:** 1.0 | Last Updated: 2025-07-11
> **Parent:** Walker AI DevTrade

---

## 01 — Big Picture

```
Mr. Walker sets direction
  → COMMANDER reads repo truth, determines lane, resolves minor issues independently
  → NEXUS executes via the appropriate role (FORGE-X / SENTINEL / BRIEFER)
  → returns to COMMANDER for review and decision
  → COMMANDER auto merges / closes / routes next lane
```

**Operating principles:**

- Tasks originate from COMMANDER
- Scope stays controlled — no silent expansion
- Repo truth is the center of all decisions
- Code truth wins over report wording
- Minor issues are resolved by COMMANDER directly — not escalated to Mr. Walker

---

## 02 — Repo Structure

### Directory Tree

```
walker-ai-team/
├── AGENTS.md                           ← highest authority (global rules)
├── PROJECT_REGISTRY.md                 ← project list + active status
├── docs/
│   ├── CLAUDE.md                       ← rules for Claude Code agent
│   ├── KNOWLEDGE_BASE.md               ← architecture, infra, API reference
│   ├── COMMANDER.md                    ← COMMANDER operating reference
│   ├── blueprint/
│   │   └── crusaderbot_final_decisions.md
│   └── templates/
│       ├── PROJECT_STATE_TEMPLATE.md
│       ├── ROADMAP_TEMPLATE.md
│       ├── TPL_INTERACTIVE_REPORT.html
│       └── REPORT_TEMPLATE_MASTER.html
├── lib/                                ← shared libraries across projects
└── projects/
    ├── polymarket/
    │   └── polyquantbot/               ← PROJECT_ROOT (active)
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

### Layer Functions

**Root repo — Global governance**

`AGENTS.md` is the highest authority and applies across all projects. `PROJECT_REGISTRY.md` is the single source for which projects exist, where they live, and which are active. These are decision-center files — not supplementary references.

**PROJECT_REGISTRY.md — Project navigation**

Agents read this first to determine where to work.

- 1 active project → NEXUS defaults to it; no tag needed
- Multiple active projects → every task must tag the project explicitly
- No tag + multiple active → NEXUS asks; never assumes

**docs/ — Knowledge, reference, blueprint, templates**

| File / Folder | Purpose |
|---|---|
| `COMMANDER.md` | COMMANDER operating reference |
| `CLAUDE.md` | Rules for Claude Code agent |
| `KNOWLEDGE_BASE.md` | Architecture, infra, API, conventions |
| `blueprint/` | Target architecture guidance |
| `templates/` | State, roadmap, and report templates |

Blueprint is a direction reference — not current truth. When blueprint and code differ: code defines current reality, blueprint defines the target.

**lib/ — Shared libraries**

Shared utilities available across all projects.

**projects/ — Multi-project workspace**

Each project has its own isolated structure under `projects/`. The active project is determined by `PROJECT_REGISTRY.md`.

**state/ — Project operational truth**

Each project maintains a `state/` folder containing three files that must always stay in sync:

| File | Role |
|---|---|
| `PROJECT_STATE.md` | Current operational condition |
| `ROADMAP.md` | Phase and milestone truth |
| `work_checklist.md` | Granular task tracking |

If one file says done and the others have not been updated — that is drift.

**Domain structure enforcement**

Inside the active `PROJECT_ROOT`, all runtime code lives within locked domain folders:
`core/`, `data/`, `strategy/`, `intelligence/`, `risk/`, `execution/`, `monitoring/`, `api/`, `infra/`, `backtest/`, `reports/`.

No `phase*/` folders. No legacy structure. No exceptions.

**reports/ — Evidence trail**

| Folder | Owner | Contents |
|---|---|---|
| `forge/` | FORGE-X | Build reports |
| `sentinel/` | SENTINEL | Validation reports |
| `briefer/` | BRIEFER | Communication artifacts |
| `archive/` | All | Reports older than 7 days |

Reports are the evidence trail used by COMMANDER for review, SENTINEL for validation, and BRIEFER for transformation.

---

## 03 — Who Does What

### Mr. Walker — Owner / Final Decision-Maker

Ultimate authority. Sets direction, priorities, and makes final calls. Involved only in decisions that genuinely require owner authority — not minor issues.

### COMMANDER — Systems Architect / Gatekeeper / Orchestrator

Operates in direct chat with Mr. Walker. All decisions, reviews, and steering happen here.

**Functions:**
- Read repo truth
- Identify active lanes
- Merge adjacent work when safe
- Route tasks to FORGE-X, SENTINEL, or BRIEFER
- Review outputs and PR packages
- Auto merge / close PRs by own decision
- Fix minor bugs, small errors, and cosmetic issues directly — no escalation

Escalates to Mr. Walker only for: large scope changes, risk decisions, capital decisions, safety concerns, or anything requiring owner authority.

### NEXUS — Multi-Agent Specialist Team

Execution team comprising FORGE-X, SENTINEL, and BRIEFER. Each role has distinct capabilities and responsibilities. NEXUS works under COMMANDER direction — receives scoped tasks, executes per role expertise, returns output for review.

NEXUS executes in separate environments (Claude Code, Codex, or other tools). NEXUS does not merge or close PRs independently — only on explicit COMMANDER instruction.

### FORGE-X — Builder / Implementer

Implement, patch, refactor, fix, update state and reports, open PR.

### SENTINEL — Validator / Auditor

Validate, audit, test, enforce safety. Active only for MAJOR tasks or on explicit COMMANDER request.

### BRIEFER — Reporter / Visualizer

HTML reports, prompt artifacts, visual summaries, UI and report transforms. Works from validated data only. Runs after the required validation path is satisfied.

---

## 04 — Operating Modes

### Normal Mode — Default

Always active unless Mr. Walker explicitly triggers Degen Mode. Used for reviews, task generation, sync, validation, and any work where scope is not fully defined.

### Degen Mode — Explicit Trigger Only

Activated only by explicit command from Mr. Walker. COMMANDER must not self-activate.

**Why it exists:** Reduces wasted time from recurring drift and review noise — while keeping repo-truth and safety gates intact.

**What it does:**
- Prioritizes implementation over repeated discussion
- Batches small safe fixes into one pass
- Skips cosmetic / non-functional noise unless explicitly requested
- Reduces micro-task fragmentation and back-and-forth
- Keeps pushing until the lane is closed or one real blocker remains

**What it does not do:**
- Override `AGENTS.md`
- Ignore repo truth
- Allow overclaiming
- Bypass safety, validation, or runtime-integrity gates
- Excuse drift

**Deactivation:** Lane complete, or Mr. Walker says stop / normal / reset.

---

## 05 — Repo Truth — Priority Order

| Priority | Source | Function |
|---|---|---|
| 1 | `AGENTS.md` | Highest authority |
| 2 | `PROJECT_REGISTRY.md` | Project navigation |
| 3 | `{PROJECT_ROOT}/state/PROJECT_STATE.md` | Operational truth |
| 4 | `{PROJECT_ROOT}/state/ROADMAP.md` | Milestone truth |
| 5 | `{PROJECT_ROOT}/state/work_checklist.md` | Granular task tracking |
| 6 | `reports/forge/`, `reports/sentinel/` | Supporting evidence |

---

## 06 — Normal Workflow

**Step A — Mr. Walker sets direction**

**Step B — COMMANDER reads repo truth**

Checks: `PROJECT_REGISTRY.md` → active project → `state/` files → active lane → blockers → tier → claim level.

**Step C — COMMANDER forms execution lane**

Adjacent open items in the same family are merged into one lane. Lane closure is preferred over fragmented progress.

**Step D — Task routed to correct role**

| Tier | Flow |
|---|---|
| MINOR | COMMANDER → FORGE-X → COMMANDER (auto merge) |
| STANDARD | COMMANDER → FORGE-X → COMMANDER (review + merge) |
| MAJOR | COMMANDER → FORGE-X → SENTINEL → COMMANDER (validate + merge) |
| BRIEFER | Runs after required validation path is satisfied |

Minor bug / error / cosmetic → COMMANDER fixes directly; no task creation.

**Step E — FORGE-X implements**

Required: work within scope, verify actual branch, update forge report and state files, commit and open PR.

---

## 07 — GitHub Workflow

### Branch

Format: `nwap/{feature}`

Branch reference must be the exact actual branch or exact PR head — never from memory or task title.

### PR Package

Every PR must carry a complete package: code + forge report + state file updates.

PR description contains: motivation, testing notes, report path, state updates, claim level, and validation tier.

COMMANDER reviews: files changed, bot comments, report, branch traceability, state drift, and claim vs actual code.

### Bot Reviews

Auto PR review bots are optional support only.

| Classification | Action |
|---|---|
| BLOCKER | Hold merge |
| MINOR_SAFE_FIX | Resolve quickly |
| IGNORE / NON-ACTIONABLE | Do not stall PR |

### Merge / Hold / Close

COMMANDER auto merges or closes by own decision. NEXUS does not merge independently.

After merge: verify result → sync state files → determine next lane.

---

## 08 — Drift & Noise

### Drift — Repo Truth Out of Sync

| Type | Description |
|---|---|
| Branch traceability drift | PR head and written references don't match |
| State / roadmap / checklist drift | The three state files say different things |
| Report / code drift | Report claims complete; actual code is narrower |
| Claim drift / overclaim | Wording implies readiness that repo truth doesn't support |
| Surface-boundary drift | Public / operator / admin paths get mixed |
| Blueprint / implementation drift | Target architecture treated as current truth |
| Phase / lane drift | Lane marked complete too early or still shown active after closure |
| Encoding / artifact drift | Mojibake, bad formatting, invalid artifact structure |

### Noise — Friction With No Material Gain

| Type | Description |
|---|---|
| Cosmetic wording debates | Style issues with no behavior impact |
| Micro-task fragmentation | One fix split into multiple tiny tasks |
| Explanation loops | Repeating context without implementing |
| Review-nit inflation | Minor comments treated as blockers |
| Redundant review churn | Evidence is clear but ceremonial re-checking continues |
| Scope creep disguised as cleanup | Small tasks expand into broad rewrites |
| User-overhead drag | Obvious low-risk decisions pushed to Mr. Walker unnecessarily |

**Impact:** Drift + noise = lane drag, over-review, branch confusion, delayed closure.

---

## 09 — Cost Discipline

### Rules

| Rule | Detail |
|---|---|
| COMMANDER compact output | Default compact. Detailed only when Mr. Walker asks or a complex decision requires it. |
| Batch over serial | One PR for multiple minor fixes. |
| Reduce explanation loops | Fix directly, report briefly. |
| NEXUS task efficiency | What + scope + ref only. Don't duplicate repo content. |
| COMMANDER self-resolve | Minor bug / error / cosmetic → fix directly. |
| Degen mode | Preferred for clear lanes — maximizes throughput without sacrificing accuracy. |
| Quick handoff | When session limit is near, generate a 5-line handoff. |

### COMMANDER Output Modes

| Mode | When | Format |
|---|---|---|
| Compact (default) | Daily ops, clear scope | Short, direct, action-oriented |
| Detailed | Mr. Walker asks, or complex decision | Full analysis + options |

### NEXUS Task Format

```
FORGE-X: [what to do]
Project: [name — only if multi-project active]
Scope:   [boundary]
Ref:     [relevant file]
```

### Quick Handoff Format

```
HANDOFF
Lane:    [active lane]
Status:  [where we stopped]
Next:    [immediate next action]
Blocker: [any — or none]
Context: [1 line max]
```

---

## 10 — Key Lessons

- Speed is lost to drift and noise — not coding difficulty
- GitHub workflow must be exact: branch, PR, report, state
- Repo truth must stay synchronized — `PROJECT_STATE.md`, `ROADMAP.md`, `work_checklist.md`, PR outcomes
- Degen mode is fast — but always subordinate to `AGENTS.md`
- Minor issues must not reach Mr. Walker — COMMANDER resolves independently
- Maximize delivery per token spent

---

`// N.W.A.P — NightWalker Autonomous Protocol`
`// Walker AI DevTrade · Bayue Walker`
