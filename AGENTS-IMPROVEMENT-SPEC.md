# AGENTS-IMPROVEMENT-SPEC.md
# Audit and improvement specification for WalkerMind OS agent configuration
# Scope: AGENTS.md, CLAUDE.md, COMMANDER.md, skill files, CI gate
# Produced by: Ona (Gitpod agent) — 2026-04-28

---

## BRAND BIBLE CONTEXT (v2.0)

The Brand Bible establishes the canonical identity for this system. Key facts that affect
this audit:

| Item | Canonical value |
|---|---|
| Platform | WalkerMind OS |
| Engine | W.A.R.P Engine (Walker Autonomous Routing Protocol) |
| Repo | `https://github.com/bayuewalker/walkermind-os` (renamed from `walker-ai-team`) |
| Director agent | WARP🔹CMD (replaces: COMMANDER) |
| Execution team | WARP🔸CORE (replaces: NEXUS) |
| Build agent | WARP•FORGE (replaces: FORGE-X) |
| Review agent | WARP•SENTINEL (replaces: SENTINEL) |
| Report agent | WARP•ECHO (replaces: BRIEFER) |
| Branch prefix | `WARP/` (replaces: `NWAP/`) |

One item from the Brand Bible rebranding checklist is still pending:
> `NWAP/` → `WARP/` cleanup in AGENTS.md, CLAUDE.md, COMMANDER.md (branch: `WARP/cleanup-legacy-refs`)

This is tracked as SPEC-14 below.

---

## FILES REVIEWED

| File | Location | Lines |
|---|---|---|
| AGENTS.md | repo root | 1601 |
| CLAUDE.md | repo root | 830 |
| COMMANDER.md | repo root | ~450+ |
| PROJECT_REGISTRY.md | repo root | ~40 |
| .agents/skills/polymarket-bot/SKILL.md | repo | ~120 |
| .agents/skills/polymarket-bot/polymarket_skill.md | repo | ~80 |
| .claude/skills/web3-polymarket/SKILL.md | repo | ~200 |
| .claude/skills/web3-polymarket/*.md | repo | 7 files |
| .github/workflows/copilot-pr-review.yml | repo | ~300 |
| .github/workflows/notify-warp-cmd.yml | repo | ~80 |

---

## WHAT IS GOOD

### 1. Authority hierarchy is explicit and enforced
AGENTS.md declares a clear, unambiguous authority chain:
`AGENTS.md > PROJECT_REGISTRY.md > PROJECT_STATE.md > ROADMAP.md > WORKTODO.md > reports > supporting docs`
Conflict resolution rules are stated for every pair. This is the strongest part of the system.

### 2. Role separation is well-defined
WARP•FORGE / WARP•SENTINEL / WARP•ECHO have distinct activation conditions, output formats,
and hard prohibitions. The "SENTINEL is a breaker, not a reviewer" framing is operationally
precise and prevents scope creep.

### 3. Validation tier system is sound
MINOR / STANDARD / MAJOR tiers with explicit routing per tier prevents over-validation
(SENTINEL on cosmetic changes) and under-validation (no SENTINEL on execution/risk changes).
The tier-to-path mapping is unambiguous.

### 4. Branch naming is locked and auto-generate is explicitly prohibited
`WARP/{feature}` format with hard prohibition on `claude/...` auto-generated names is
correct. The worktree/detached HEAD edge case is handled explicitly.

### 5. Report format is fully specified
6-section forge report with mandatory metadata (Validation Tier, Claim Level, Validation Target,
Not in Scope, Suggested Next Step) gives SENTINEL and WARP🔹CMD a consistent review surface.
Done output format is machine-checkable.

### 6. CI gate (copilot-pr-review.yml) is well-calibrated
Hard blockers (B1, B2, B4–B8, B10–B12) are correctly scoped to objective, automatable checks.
Warnings (B3, B9) are correctly deferred to SENTINEL rather than blocking on false positives.
The gate comment templates are clear and actionable.

### 7. Encoding rules are thorough
UTF-8 without BOM, explicit `encoding='utf-8'` on all Python file I/O, locale requirements,
mojibake detection patterns — this level of detail prevents a real class of silent corruption bugs.

### 8. Cost efficiency rules in CLAUDE.md are practical
Read-only-what-you-need, no re-reading, no full-file cat on large files, no filler output —
these rules directly reduce token cost and context bloat.

### 9. Chunk-based execution model prevents timeouts
Hard limits (5 files/chunk, 8 reads/chunk, 6 tool calls/chunk) with explicit continuation
signaling prevent the most common failure mode in long agent tasks.

### 10. web3-polymarket skill is well-structured
Modular reference files (authentication.md, order-patterns.md, etc.) with a lean SKILL.md
index that loads sub-files on demand. Correct pattern for a large domain skill.

---

## WHAT IS MISSING

### M1. Skill files are not registered in AGENTS.md or CLAUDE.md
`.agents/skills/polymarket-bot/` and `.claude/skills/web3-polymarket/` exist and are used,
but neither AGENTS.md nor CLAUDE.md mentions them. Agents have no authoritative guidance on:
- which skill to load for which task type
- which skill takes precedence when both cover Polymarket
- whether `.agents/skills/` or `.claude/skills/` is the canonical location

**Impact:** Agents either ignore skills (wasted investment) or load both (context bloat and
potential contradiction).

### M2. No skill conflict resolution rule
`.agents/skills/polymarket-bot/SKILL.md` and `.claude/skills/web3-polymarket/SKILL.md` both
cover Polymarket API and order execution. They have different architectures (single-strategy
vs multi-strategy), different branch naming conventions (`feature/forge/` vs `WARP/`), and
different risk config detail levels. No rule exists to resolve which is authoritative.

**Impact:** An agent loading both gets contradictory branch naming and architecture guidance.

### M3. COMMANDER.md references four skills that do not exist in the repo
`gh-fix-ci`, `remote-tests`, `codex-pr-body`, `gh-address-comments` are listed as available
skills in COMMANDER.md but no corresponding files exist anywhere in the repo.

**Impact:** WARP🔹CMD may instruct agents to use skills that cannot be loaded, causing silent
fallback to unguided behavior.

### M4. No archive/rotation policy for reports
AGENTS.md states reports older than 7 days go to `reports/archive/` but defines no mechanism,
trigger, or responsible role for the move. No CI job or agent step enforces this.

**Impact:** `reports/forge/` and `reports/sentinel/` accumulate indefinitely. "Latest relevant
report" becomes ambiguous when 20+ reports exist.

### M5. No explicit onboarding path for a new agent/tool
When a new agent platform (e.g. Codex, a new Claude environment, a new CI runner) is added,
there is no checklist for what it must read, what environment variables it must set, and how
it registers itself. The encoding rules (LANG, LC_ALL, PYTHONIOENCODING) are defined but
there is no "new runner setup" section that consolidates them.

### M6. No definition of "priority done" vs "phase done" for the SENTINEL activation rule
AGENTS.md states "Normal → WARP•SENTINEL per priority done" but does not define what
constitutes a "priority" boundary. WORKTODO.md and ROADMAP.md use different granularity.
An agent cannot reliably determine when a priority is done without a definition.

### M7. No rollback or revert procedure
AGENTS.md defines what to do when drift is detected (STOP, report) but has no procedure for
reverting a bad merge, rolling back a state file to a previous known-good version, or
recovering from a corrupted PROJECT_STATE.md.

### M8. WARP•ECHO FRONTEND mode has no output path or branch convention
REPORT mode has `{PROJECT_ROOT}/reports/briefer/{feature}.html` and `WARP/briefer-{purpose}`.
PROMPT mode has no path (output is chat only, which is correct). FRONTEND mode has no defined
output path, no branch convention, and no PR format. An agent implementing FRONTEND mode has
no guidance on where to put the files.

---

## WHAT IS WRONG

### W1. Stale repo reference in .agents/skills/polymarket-bot/SKILL.md
The `.agents/skills/polymarket-bot/SKILL.md` states `Repo: github.com/bayuewalker/walker-ai-team`.
The GitHub repo was renamed to `walkermind-os` as part of the Brand Bible v2.0 rebranding
(Brand Bible §9 — `walker-ai-team (repo)` → `walkermind-os` ❌ Deprecated).
AGENTS.md and CLAUDE.md correctly reference `https://github.com/bayuewalker/walkermind-os`.
The local workspace directory `/workspaces/walker-ai-team` is a stale Gitpod clone path
and does not reflect the actual repo name.

**Severity:** Low. Affects only the skill file, not the authority files.

**Fix:** Update `Repo:` in `.agents/skills/polymarket-bot/SKILL.md` to `github.com/bayuewalker/walkermind-os`.

### W2. CLAUDE.md self-declares wrong location
CLAUDE.md header says `# Location: CLAUDE.md` (repo root) but the KEY FILE LOCATIONS section
says `docs/CLAUDE.md <- this file`. The file is at repo root. `docs/CLAUDE.md` does not exist.

**Severity:** Low-Medium. An agent following the KEY FILE LOCATIONS table will look for
CLAUDE.md in `docs/` and fail to find it, then either error or fall back to no rules.

**Fix:** Remove `docs/CLAUDE.md` from KEY FILE LOCATIONS. Replace with `CLAUDE.md` (repo root).

### W3. .agents/skills/polymarket-bot uses forbidden branch naming convention
`.agents/skills/polymarket-bot/SKILL.md` PUSH RULES section states:
`Branch: feature/forge/[task-name]`
This directly contradicts AGENTS.md and CLAUDE.md which mandate `WARP/{feature}` exclusively
and explicitly list `feature/...` as a wrong format.

**Severity:** High. An agent loading this skill will create branches in the wrong format,
which the CI gate does not filter (notify-warp-cmd.yml only triggers on `WARP/` branches,
so wrong-format branches get no notification and no gate).

**Fix:** Update `.agents/skills/polymarket-bot/SKILL.md` PUSH RULES to use `WARP/{feature}`.

### W4. PROJECT_REGISTRY.md uses "NEXUS" — undefined role name
PROJECT_REGISTRY.md RULES section says "1 project active → NEXUS defaults to it" and
"No tag + multi → NEXUS asks, never assumes". NEXUS is not defined anywhere in AGENTS.md,
CLAUDE.md, or COMMANDER.md. The correct role name is WARP🔹CMD.

**Severity:** Medium. An agent reading PROJECT_REGISTRY.md encounters an undefined actor
and cannot map it to the authority chain.

**Fix:** Replace `NEXUS` with `WARP🔹CMD` in PROJECT_REGISTRY.md.

### W5. CI gate (copilot-pr-review.yml) enforces old report naming format
B2 check validates report names against `^[0-9]+_[0-9]+_[a-z0-9_]+\.md$`
(e.g. `24_01_validation-engine-core.md`). AGENTS.md and CLAUDE.md mandate the new format:
`{feature}.md` — short hyphen-separated slug, no phase prefix, no increment number.
CLAUDE.md explicitly marks `phase24_01_validation-engine-core.md` as **Wrong**.

**Severity:** High. Every correctly-named forge report under the current AGENTS.md rules
will fail B2 and block the PR. The gate enforces the old format that the rules prohibit.

**Fix:** Update B2 regex to `^[a-z][a-z0-9-]+\.md$` (hyphen-separated slug, no phase prefix).

### W6. CI gate B6 domain structure allowlist is incomplete
B6 blocks files outside the domain structure but the allowlist does not include:
- `COMMANDER.md` (repo root — present and modified)
- `PROJECT_REGISTRY.md` (repo root — present and modified)
- `CHANGELOG.md` (repo root level — referenced in state)
- `.agents/` directory (skill files live here)
- `pytest.ini` (present at repo root)

A PR that updates COMMANDER.md or PROJECT_REGISTRY.md will be blocked by B6.

**Severity:** Medium. Legitimate maintenance PRs on root-level governance files will be
incorrectly blocked.

**Fix:** Add `COMMANDER.md`, `PROJECT_REGISTRY.md`, `CHANGELOG.md`, `.agents/`, `pytest.ini`
to the B6 allowlist.

### W7. AGENTS.md contains a full duplicate of PROJECT_REGISTRY.md
The PROJECT REGISTRY section in AGENTS.md (lines ~220–250) duplicates the content of
`PROJECT_REGISTRY.md` exactly. AGENTS.md itself states that `PROJECT_REGISTRY.md` is the
authoritative source for project list and active status (rule priority #2). The duplicate
in AGENTS.md will drift from PROJECT_REGISTRY.md over time and create a conflict that
AGENTS.md's own conflict rules say to treat as drift requiring a STOP.

**Severity:** Medium. Creates a guaranteed future drift condition between two files that
are both declared authoritative for the same data.

**Fix:** Replace the PROJECT REGISTRY section in AGENTS.md with a single pointer:
`Project list and active status: see PROJECT_REGISTRY.md (repo root).`

### W8. WARP•SENTINEL activation rule has an internal contradiction
AGENTS.md WARP•SENTINEL ACTIVATION RULE section states:
`Normal → WARP•SENTINEL per priority done`
But the OPERATING MODEL section and CLAUDE.md both state:
`WARP•SENTINEL runs only for MAJOR tasks or explicit WARP🔹CMD audit request`

These are contradictory. "Per priority done" implies SENTINEL runs after every priority
regardless of tier. "MAJOR only" means SENTINEL only runs when the tier is MAJOR.

**Severity:** Medium. Agents reading different sections will apply different activation
thresholds, leading to either over-validation (SENTINEL on every MINOR priority) or
under-validation (SENTINEL skipped on STANDARD priorities that complete a milestone).

**Fix:** Reconcile by clarifying that "per priority done" means: after a priority closes,
if any task in that priority was MAJOR tier, SENTINEL runs. If all tasks were MINOR/STANDARD,
WARP🔹CMD review only. Add this clarification to the SENTINEL ACTIVATION RULE section.

---

## IMPROVEMENT SPEC

Each item below is a concrete, actionable change. Items are ordered by severity (high first).

---

### SPEC-01 — Fix report naming regex in CI gate
**File:** `.github/workflows/copilot-pr-review.yml`
**Section:** B2 check
**Change:** Replace regex `^[0-9]+_[0-9]+_[a-z0-9_]+\.md$` with `^[a-z][a-z0-9-]+\.md$`
**Rationale:** W5. Current regex blocks every correctly-named report under current AGENTS.md rules.
**Validation:** Test with `echo "wallet-state-read-boundary.md" | grep -qE "^[a-z][a-z0-9-]+\.md$"` → match.
Test with `echo "24_01_validation-engine-core.md" | grep -qE "^[a-z][a-z0-9-]+\.md$"` → no match.

---

### SPEC-02 — Fix branch naming in .agents/skills/polymarket-bot/SKILL.md
**File:** `.agents/skills/polymarket-bot/SKILL.md`
**Section:** PUSH RULES
**Change:** Replace `Branch: feature/forge/[task-name]` with `Branch: WARP/{feature-slug}`
**Rationale:** W3. Skill instructs agents to use a branch format that AGENTS.md explicitly prohibits.

---

### SPEC-03 — Fix stale repo reference in .agents/skills/polymarket-bot/SKILL.md
**File:** `.agents/skills/polymarket-bot/SKILL.md`
**Section:** Project Context header
**Change:** Replace `**Repo:** github.com/bayuewalker/walker-ai-team` with
`**Repo:** github.com/bayuewalker/walkermind-os`
**Rationale:** W1. Repo was renamed to `walkermind-os` per Brand Bible v2.0. Skill file still references the deprecated name.

---

### SPEC-04 — Fix CLAUDE.md self-location claim
**File:** `CLAUDE.md`
**Section:** KEY FILE LOCATIONS
**Change:** Replace `docs/CLAUDE.md <- this file` with `CLAUDE.md <- this file (repo root)`
**Rationale:** W2. File is at repo root, not docs/. docs/CLAUDE.md does not exist.

---

### SPEC-05 — Fix NEXUS reference in PROJECT_REGISTRY.md
**File:** `PROJECT_REGISTRY.md`
**Section:** RULES
**Change:** Replace both occurrences of `NEXUS` with `WARP🔹CMD`
**Rationale:** W4. NEXUS is undefined in the authority chain.

---

### SPEC-06 — Expand B6 allowlist in CI gate
**File:** `.github/workflows/copilot-pr-review.yml`
**Section:** B6 check (OUTSIDE variable grep exclusions)
**Change:** Add the following exclusion lines:
```
| grep -v "^COMMANDER\.md$" \
| grep -v "^PROJECT_REGISTRY\.md$" \
| grep -v "^CHANGELOG\.md$" \
| grep -v "^AGENTS-IMPROVEMENT-SPEC\.md$" \
| grep -v "^\.agents/" \
| grep -v "^pytest\.ini$" \
```
**Rationale:** W6. Legitimate root-level governance files are incorrectly blocked.

---

### SPEC-07 — Remove duplicate PROJECT REGISTRY from AGENTS.md
**File:** `AGENTS.md`
**Section:** PROJECT REGISTRY (the table section, not the navigation rules)
**Change:** Replace the full project table and status definitions with:
```
Project list, active status, and current focus: see PROJECT_REGISTRY.md (repo root).
Navigation rules:
- 1 active project -> WARP🔸CORE defaults to it, no tag needed
- Multi-project active -> every task must tag the project
- No tag + multi-project active -> WARP🔸CORE asks, never assumes
- State per project -> self-contained in {PROJECT_ROOT}/state/
```
Keep the navigation rules in AGENTS.md (they are behavioral rules, not data).
Remove the table (it is data that belongs in PROJECT_REGISTRY.md only).
**Rationale:** W7. Duplicate data source guarantees future drift.

---

### SPEC-08 — Reconcile SENTINEL activation rule
**File:** `AGENTS.md`
**Section:** WARP•SENTINEL ACTIVATION RULE
**Change:** Add a clarifying sentence after the "Simple rule" block:
```
Clarification on "priority done":
A priority is considered done when all tasks in that priority are merged.
SENTINEL runs after a priority closes IF any task in that priority was MAJOR tier.
If all tasks in the priority were MINOR or STANDARD, WARP🔹CMD review only — no SENTINEL.
```
**Rationale:** W8. Resolves the contradiction between "per priority done" and "MAJOR only".

---

### SPEC-09 — Register skill files in AGENTS.md and CLAUDE.md
**Files:** `AGENTS.md` (REPO STRUCTURE and KEY FILE LOCATIONS sections), `CLAUDE.md` (KEY FILE LOCATIONS)
**Change:**

In AGENTS.md REPO STRUCTURE, add under repo root:
```
├── .agents/
│   └── skills/
│       └── polymarket-bot/    <- Polymarket bot builder skill (WARP•FORGE)
├── .claude/
│   └── skills/
│       └── web3-polymarket/   <- Polymarket API integration skill (all roles)
```

In AGENTS.md KEY FILE LOCATIONS, add:
```
.agents/skills/polymarket-bot/SKILL.md     <- bot builder patterns, risk config, formulas
.claude/skills/web3-polymarket/SKILL.md    <- Polymarket API auth, orders, WebSocket, CTF
```

In CLAUDE.md BEFORE EVERY TASK, add step 8:
```
8. Load .claude/skills/web3-polymarket/SKILL.md if task touches Polymarket API,
   authentication, order placement, WebSocket, CTF, or bridge operations.
   Load .agents/skills/polymarket-bot/SKILL.md if task touches bot architecture,
   signal engine, risk config, capital allocation, or execution patterns.
```

Add a skill precedence rule:
```
Skill precedence (Polymarket tasks):
- .claude/skills/web3-polymarket/ -> authoritative for API protocol, auth, SDK usage
- .agents/skills/polymarket-bot/ -> authoritative for bot architecture, risk rules, formulas
- When both apply: use web3-polymarket for API calls, polymarket-bot for system design
- On conflict: AGENTS.md hard rules win over both skills
```
**Rationale:** M1, M2. Skills are invisible to agents without registration.

---

### SPEC-10 — Remove or stub ghost skills from COMMANDER.md
**File:** `COMMANDER.md`
**Section:** Available skills
**Change:** Either:
  - (Option A) Remove `gh-fix-ci`, `remote-tests`, `codex-pr-body`, `gh-address-comments`
    and replace with the two actual skills: `polymarket-bot` and `web3-polymarket`
  - (Option B) Mark them as `[NOT YET CREATED]` with a note that they are planned
**Recommended:** Option A — remove ghost references, add real ones.
**Rationale:** M3. WARP🔹CMD instructing agents to use non-existent skills causes silent failure.

---

### SPEC-11 — Define report archive trigger
**File:** `AGENTS.md`
**Section:** CORE PRINCIPLE (or new REPORT LIFECYCLE section)
**Change:** Add:
```
Report lifecycle:
- Active reports: {PROJECT_ROOT}/reports/forge/ and reports/sentinel/
- Archive trigger: when a lane is closed (CHANGELOG.md updated), WARP•FORGE moves
  all reports from that lane to {PROJECT_ROOT}/reports/archive/
- Archive is manual — no automated job
- "Latest relevant report" = most recent file in reports/forge/ by mtime, not by filename
- WARP🔹CMD may instruct archive at any time; WARP•FORGE executes
```
**Rationale:** M4. Without a defined trigger, reports accumulate and "latest" becomes ambiguous.

---

### SPEC-12 — Add WARP•ECHO FRONTEND output path and branch convention
**File:** `AGENTS.md` and `CLAUDE.md`
**Section:** ROLE: WARP•ECHO — VISUALIZE, MODE: FRONTEND
**Change:** Add after the FRONTEND stack definition:
```
Output path: {PROJECT_ROOT}/reports/briefer/frontend/{feature}/
Branch: WARP/frontend-{purpose}
Commit: frontend: {feature}
PR title: frontend: {feature} — [brief description]
Entry point: index.html or App.tsx at output path root
```
**Rationale:** M8. FRONTEND mode has no output contract, making it unverifiable.

---

### SPEC-13 — Add new runner setup checklist
**File:** `AGENTS.md`
**Section:** ENCODING RULE (append as subsection) or new RUNNER SETUP section
**Change:** Add:
```
### New runner / environment setup (run before first file write)
1. Verify locale: `locale` must show C.UTF-8 or en_US.UTF-8
2. Set if missing:
   export LANG=C.UTF-8
   export LC_ALL=C.UTF-8
   export PYTHONIOENCODING=utf-8
3. Configure git:
   git config --global core.quotepath false
   git config --global core.autocrlf input
4. Verify branch: git rev-parse --abbrev-ref HEAD
5. Read AGENTS.md, PROJECT_REGISTRY.md, PROJECT_STATE.md before any file operation
If any step fails: STOP, report to WARP🔹CMD, do not proceed.
```
**Rationale:** M5. Encoding rules exist but are scattered. New runners need a single checklist.

---

### SPEC-14 — Complete pending Brand Bible NWAP cleanup
**Files:** `AGENTS.md`, `CLAUDE.md`, `COMMANDER.md`
**Branch:** `WARP/cleanup-legacy-refs` (already declared in Brand Bible checklist)
**Change:** Grep for any remaining `NWAP/` references and replace with `WARP/`.
Also verify no remaining occurrences of deprecated agent names: COMMANDER, NEXUS, FORGE-X, BRIEFER.
```bash
grep -rn "NWAP/\|COMMANDER\b\|NEXUS\b\|FORGE-X\|BRIEFER\b" AGENTS.md CLAUDE.md COMMANDER.md
```
Note: `COMMANDER.md` as a filename is fine — the deprecated term is the role name "COMMANDER"
used to refer to the agent, not the filename itself.
**Rationale:** Brand Bible §10 — this item is explicitly marked as pending in the rebranding checklist.

---

## SUMMARY TABLE

**Must fix before next MAJOR task:** SPEC-01, SPEC-02
**Fix in next maintenance lane:** SPEC-03 through SPEC-08, SPEC-14 (pending Brand Bible item)
**Backlog (low risk):** SPEC-09 through SPEC-13

| ID | Severity | Type | File(s) | Description |
|---|---|---|---|---|
| SPEC-01 | High | Bug | copilot-pr-review.yml | CI gate blocks all correctly-named reports |
| SPEC-02 | High | Bug | .agents/skills/.../SKILL.md | Skill uses forbidden branch format |
| SPEC-03 | Low | Bug | .agents/skills/.../SKILL.md | Stale repo name (walker-ai-team → walkermind-os) |
| SPEC-04 | Low | Bug | CLAUDE.md | Wrong self-location in KEY FILE LOCATIONS |
| SPEC-05 | Medium | Bug | PROJECT_REGISTRY.md | Undefined role name NEXUS |
| SPEC-06 | Medium | Bug | copilot-pr-review.yml | B6 blocks legitimate root-level files |
| SPEC-07 | Medium | Drift risk | AGENTS.md | Duplicate project registry data |
| SPEC-08 | Medium | Contradiction | AGENTS.md | SENTINEL activation rule is ambiguous |
| SPEC-09 | Medium | Missing | AGENTS.md, CLAUDE.md | Skills not registered or routed |
| SPEC-10 | Medium | Missing | COMMANDER.md | Ghost skill references |
| SPEC-11 | Low | Missing | AGENTS.md | No report archive trigger defined |
| SPEC-12 | Low | Missing | AGENTS.md, CLAUDE.md | FRONTEND mode has no output contract |
| SPEC-13 | Low | Missing | AGENTS.md | No consolidated new-runner setup checklist |
| SPEC-14 | Medium | Pending | AGENTS.md, CLAUDE.md, COMMANDER.md | Brand Bible NWAP→WARP cleanup not yet done |
