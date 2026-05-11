# WARP•FORGE REPORT — issue-label-convention

Branch            : WARP/issue-label-convention
Validation Tier   : MINOR
Claim Level       : FOUNDATION
Validation Target : issue label convention in COMMANDER.md
Not in Scope      : runtime, state files, shortcut commands, CI gate, AGENTS.md, CLAUDE.md
Suggested Next Step: WARP🔹CMD review and merge

---

## 1. What was built

Updated GitHub Issue label convention in `COMMANDER.md` GITHUB ISSUE AUTO-CREATE RULE from the generic `warp-core` label to agent-specific labels: `warp-forge` / `warp-sentinel` / `warp-echo`. The role label must match the executing agent.

Single-file docs-only change. No runtime, state, or operational truth touched.

## 2. Current system architecture

Issue labelling authority (unchanged):
- `COMMANDER.md` GITHUB ISSUE AUTO-CREATE RULE defines per-task issue creation contract for WARP🔹CMD task dispatch (STANDARD / MAJOR tiers)

After this lane, every auto-created issue must carry two labels:
- Agent label: `warp-forge` / `warp-sentinel` / `warp-echo` (matches executing role)
- Tier label: `major` / `standard`

This makes filtering and traceability per-agent possible without parsing issue titles.

## 3. Files created / modified

Modified:
- `COMMANDER.md` — GITHUB ISSUE AUTO-CREATE RULE Labels subsection only

Created: none.

## 4. What is working

- Label convention now distinguishes the executing agent role explicitly
- Tier labels (`major` / `standard`) preserved
- Surrounding rule structure (`### When to create`, `### Issue format`, `### Auto-close behavior`, `### Commit message format`) preserved verbatim

## 5. Known issues

- None.

## 6. What is next

- WARP🔹CMD review of this MINOR PR
- No state file updates required — docs-only change with no operational truth impact
- Follow-up consideration outside scope: GitHub repo may need the three new label values (`warp-forge`, `warp-sentinel`, `warp-echo`) created if not already present, plus eventual deprecation of `warp-core`. Flag for a future infra lane.
