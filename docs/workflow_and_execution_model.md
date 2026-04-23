# N.W.A.P — Operational Protocol & Execution Model

> **// DOCUMENT_TYPE:** Internal operational reference
> **// AUTHORITY:** Supporting document — `AGENTS.md` is the authoritative rule source
> **// VERSION:** 1.0 | Last Updated: 2025-07-11
> **// PARENT:** Walker AI DevTrade

---

## // SECTION_01 — BIG_PICTURE

Mr. Walker sets direction
→ COMMANDER reads repo truth, determines lane, resolves minor issues independently
→ NEXUS executes via the appropriate role (FORGE-X / SENTINEL / BRIEFER)
→ returns to COMMANDER for review and decision
→ COMMANDER auto merges / closes / routes next lane

**Principles:**

- Tasks come from COMMANDER
- Scope stays controlled
- Repo truth = center of all decisions
- Code truth wins over report wording
- Minor issues = COMMANDER handles directly — do not escalate to Mr. Walker

---

## // SECTION_02 — REPO_STRUCTURE

### // TREE

```text
walker-ai-team/
├── AGENTS.md                          ← highest authority (global rules)
├── PROJECT_REGISTRY.md                ← project list + active status
├── docs/
│   ├── CLAUDE.md                      ← rules for Claude Code agent
│   ├── KNOWLEDGE_BASE.md              ← architecture, infra, API reference
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

### // LAYER_FUNCTIONS

**Root repo — Global governance**

- `AGENTS.md` = highest authority, applies across all projects
- `PROJECT_REGISTRY.md` = project list + active status

Decision center. Not supplementary files.

**PROJECT_REGISTRY.md — Project navigation**

Single file: which projects exist, where they live, which are active. Agent reads this → immediately knows where to work.

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

Blueprint is a direction reference — not current truth. When blueprint and code differ: code = current reality, blueprint = target direction.

**lib/ — Shared libraries**

Shared utilities across projects.

**projects/ — Multi-project workspace**

Repo is designed for multiple workstreams. Each project has its own structure under `projects/`. Active project determined by `PROJECT_REGISTRY.md`.

**state/ — Project operational truth**

Each project has its own `state/` folder under PROJECT_ROOT:

- `PROJECT_STATE.md` — current operational condition
- `ROADMAP.md` — phase / milestone truth
- `work_checklist.md` — granular task tracking

These three files must always stay in sync. If one says done and the others haven't been updated — that is drift.

**Domain structure enforcement**

Inside the active PROJECT_ROOT, folder structure follows the domain structure enforced by `AGENTS.md`: `core/`, `data/`, `strategy/`, `intelligence/`, `risk/`, `execution/`, `monitoring/`, `api/`, `infra/`, `backtest/`, and `reports/`. No `phase*/` folders or legacy structure allowed.

**reports/ — Evidence trail**

Each project has its own `reports/` folder under PROJECT_ROOT:

- `forge/` — build reports from FORGE-X
- `sentinel/` — validation reports from SENTINEL
- `briefer/` — communication artifacts from BRIEFER
- `archive/` — reports older than 7 days moved here

Reports are the evidence trail used by COMMANDER for review, SENTINEL for validation, and BRIEFER for transformation.

---

## // SECTION_03 — WHO_DOES_WHAT

### Mr. Walker

**// ROLE:** Owner / Final Decision-Maker

Ultimate authority. Sets direction, priorities, and makes final calls. Mr. Walker is involved only in decisions that genuinely require owner authority — not minor issues.

### COMMANDER

**// ROLE:** Systems Architect / Gatekeeper / Orchestrator

COMMANDER operates in direct chat with Mr. Walker — decisions, reviews, and steering happen here.

Functions:
- Read repo truth
- Identify active lanes
- Merge adjacent work when safe
- Route tasks to FORGE-X, SENTINEL, or BRIEFER
- Review outputs
- Auto merge / close PRs by own decision
- Fix minor bugs, small errors, cosmetic issues directly — no escalation

Escalate to Mr. Walker only for: large scope, risk, capital, safety, or decisions requiring owner authority.

### NEXUS

**// ROLE:** Multi-Agent Specialist Team

Execution team: FORGE-X, SENTINEL, BRIEFER. Each has distinct capabilities and responsibilities. NEXUS works under COMMANDER direction — receives scoped tasks, executes per role expertise, returns output for review.

NEXUS executes in separate environments: Claude Code, Codex, or other tools as needed. NEXUS does not merge / close PRs independently — only executes on COMMANDER instruction.

### FORGE-X

**// ROLE:** Builder / Implementer / Refactor / Fix Specialist

Implement, patch, refactor, fix, update state / reports, open PR.

### SENTINEL

**// ROLE:** Validator / Auditor / Safety Enforcer

Validate, audit, test, enforce safety. Active only for MAJOR tasks or on explicit COMMANDER request.

### BRIEFER

**// ROLE:** Reporter / Visualizer / Communication Layer

HTML reports, prompt artifacts, visual summaries, UI / report transforms. Works from validated data only. Runs after required validation path is satisfied.

---

## // SECTION_04 — OPERATING_MODES

### Normal Mode — Default

Always active unless Mr. Walker explicitly triggers degen mode.

Used for: reviews, task generation, sync, validation, work where scope isn't fully defined.

### Degen Mode — Explicit Trigger Only

Only active when Mr. Walker triggers it explicitly. COMMANDER must not self-activate.

**// WHY_IT_EXISTS:**
Reduces wasted time from recurring drift and review noise — while keeping repo-truth and safety gates intact.

**// WHAT_IT_DOES:**
- Prioritizes implementation over repeated discussion
- Batches small safe fixes into one pass
- Skips cosmetic / non-functional noise unless explicitly requested
- Reduces micro-task fragmentation
- Minimizes back-and-forth
- Keeps pushing until lane is closed or one real blocker remains

**// WHAT_IT_DOES_NOT_DO:**
- Override `AGENTS.md`
- Ignore repo truth
- Allow overclaiming
- Bypass safety, validation, or runtime-integrity gates
- Excuse drift

**// DEACTIVATION:** Lane complete, or Mr. Walker says stop / normal / reset.

---

## // SECTION_05 — REPO_TRUTH

Priority order — source of system truth before any work begins:

| Priority | Source | Function |
|----------|--------|----------|
| 1 | `AGENTS.md` | Highest authority |
| 2 | `PROJECT_REGISTRY.md` | Project navigation |
| 3 | `{PROJECT_ROOT}/state/PROJECT_STATE.md` | Operational truth |
| 4 | `{PROJECT_ROOT}/state/ROADMAP.md` | Milestone truth |
| 5 | `{PROJECT_ROOT}/state/work_checklist.md` | Granular task tracking |
| 6 | `reports/forge/`, `reports/sentinel/` | Supporting evidence |

---

## // SECTION_06 — NORMAL_WORKFLOW

**Step A — Mr. Walker sets direction**

**Step B — COMMANDER reads repo truth**
Checks: `PROJECT_REGISTRY.md` → active project → `state/` files → active lane → blockers → tier → claim level.

**Step C — COMMANDER forms execution lane**
Adjacent open items in the same family → merge into one lane. Prefer lane closure over fragmented progress.

**Step D — Task routed to correct role**

| Tier | Flow |
|------|------|
| MINOR | COMMANDER → FORGE-X → COMMANDER (auto merge) |
| STANDARD | COMMANDER → FORGE-X → COMMANDER (review + merge) |
| MAJOR | COMMANDER → FORGE-X → SENTINEL → COMMANDER (validate + merge) |
| BRIEFER | Runs after required validation path is satisfied |

Minor bug / error / cosmetic → COMMANDER fixes directly, skips task creation.

**Step E — FORGE-X implements**
Required: work within scope, verify actual branch, update forge report + state files, commit and open PR.

---

## // SECTION_07 — GITHUB_WORKFLOW

### // BRANCH

Format: `feature/{feature}`

Applies to all environments. Branch reference must be exact actual branch / exact PR head — never from memory or task title.

### // COMMIT_REPORT_STATE

PR must carry a complete package: code + forge report + state files update.

### // PULL_REQUEST

PR contains: motivation, testing, report path, state updates, claim / tier context.

COMMANDER reviews: files changed, bot comments, report, branch traceability, state drift, claim vs actual code.

### // BOT_REVIEWS

Auto PR review bots = optional support only.

COMMANDER classifies:

| Classification | Action |
|---------------|--------|
| BLOCKER | Hold merge |
| MINOR_SAFE_FIX | Resolve quickly |
| IGNORE / NON-ACTIONABLE | Do not stall PR |

### // MERGE_HOLD_CLOSE

COMMANDER auto merges / closes by own decision. NEXUS does not merge independently.

After merge: verify result → sync state files → determine next lane.

---

## // SECTION_08 — DRIFT_AND_NOISE

### // DRIFT

Drift = repo truth out of sync.

- **Branch traceability drift** — PR head and written references don't match
- **State / roadmap / checklist drift** — `PROJECT_STATE.md`, `ROADMAP.md`, `work_checklist.md` say different things
- **Report / code drift** — report claims complete, actual code is narrower
- **Claim drift / overclaim** — wording implies readiness that repo truth doesn't support
- **Surface-boundary drift** — public / operator / admin paths get mixed
- **Blueprint / implementation drift** — target architecture treated as current truth
- **Phase / lane drift** — lane marked complete too early or still shown active after closure
- **Encoding / artifact drift** — mojibake, bad formatting, invalid artifact structure

### // NOISE

Noise = small friction with no material improvement.

- **Cosmetic wording debates** — style issues with no behavior impact
- **Micro-task fragmentation** — one fix split into multiple tiny tasks
- **Explanation loops** — repeating context without implementing
- **Review-nit inflation** — minor comments treated as blockers
- **Redundant review churn** — evidence is clear but ceremonial re-checking continues
- **Scope creep disguised as cleanup** — small tasks expand into broad rewrites
- **User-overhead drag** — too many obvious low-risk decisions pushed to Mr. Walker

### // IMPACT

Drift + noise = lane drag, over-review, branch confusion, delayed closure.

---

## // SECTION_09 — COST_DISCIPLINE

### // RULES

| Rule | Detail |
|------|--------|
| COMMANDER compact output | Default compact. Detailed only when Mr. Walker asks or complex decision. |
| Batch over serial | One PR for multiple minor fixes. |
| Reduce explanation loops | Fix directly, report briefly. |
| NEXUS task efficiency | What + scope + ref only. Don't duplicate repo content. |
| COMMANDER self-resolve | Minor bug / error / cosmetic → fix directly. |
| Degen mode = cost saver | Preferred for clear lanes. |
| Quick handoff | When session limit is near, generate 5-line handoff. |

### // COMMANDER_OUTPUT_MODES

| Mode | When | Format |
|------|------|--------|
| Compact (default) | Daily ops, clear scope | Short, direct, action-oriented |
| Detailed | Mr. Walker asks, complex decision | Full analysis + options |

### // NEXUS_TASK_FORMAT

```
FORGE-X: [what to do]
Project: [name — only if multi-project active]
Scope: [boundary]
Ref: [relevant file]
```

### // QUICK_HANDOFF

```
📍 HANDOFF
Lane: [active lane]
Status: [where we stopped]
Next: [immediate next action]
Blocker: [any — or none]
Context: [1 line max]
```

---

## // SECTION_10 — KEY_LESSONS

- Speed is lost to drift and noise — not coding difficulty
- GitHub workflow must be exact: branch, PR, report, state
- Repo truth must stay synchronized — `PROJECT_STATE.md`, `ROADMAP.md`, `work_checklist.md`, PR outcomes
- Degen mode is fast — but always subordinate to `AGENTS.md`
- Minor issues must not reach Mr. Walker — COMMANDER resolves independently
- Maximize delivery per token spent

---

`// N.W.A.P — NightWalker Autonomous Protocol`
`// Walker AI DevTrade · Bayue Walker`
`// End of document.`
