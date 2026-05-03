# WARP•FORGE Report — governance-docs-sync

Last Updated: 2026-05-03 18:30 Asia/Jakarta
Branch: WARP/governance-docs-sync
Tier: MINOR
Claim Level: FOUNDATION

---

## 1. What was changed

Governance docs cross-file sync per WARP🔹CMD audit (v2.6). Single batched MINOR lane covering version alignment, missing rule mirroring, COMMANDER.md path drift fix, and 8 governance improvements. Zero runtime impact.

### AGENTS.md (2.5 → 2.6)
- Path drift fixed: COMMANDER.md is at repo root, not under `docs/`.
  - REPO STRUCTURE tree: COMMANDER.md moved out of `docs/` and listed as a root sibling alongside AGENTS.md / PROJECT_REGISTRY.md / CLAUDE.md.
  - KEY FILE LOCATIONS: COMMANDER.md regrouped with root-level files and annotated `(repo root)`.
  - Global pass: zero remaining `docs/COMMANDER.md` references in AGENTS.md.
- 4 new authoritative sections added:
  1. PROJECT AWARENESS RULE (AUTHORITATIVE) — placed after PROJECT REGISTRY. Pre-action requirement, project resolution flow, dynamic `{PROJECT_ROOT}` resolution, cross-project bleed prevention.
  2. AGENT IDENTITY VERIFICATION (AUTHORITATIVE) — placed after PROJECT AWARENESS RULE. Role + execution environment + active project at session start, role-switch rules, anti-impersonation.
  3. ESCALATION MATRIX — placed after FAILURE CONDITIONS. Severity table covering DRIFT / REPO-TRUTH DEFECT / SAFETY-CRITICAL / CROSS-PROJECT BLEED / UNRESOLVED BLOCKER (after 2 SENTINEL runs).
  4. PR SIZE RULE (AUTHORITATIVE — UNIVERSAL) — placed after Task Chunking Protocol. Universal split criteria, merge-order declaration, dependency notation. Tooling-specific pagination explicitly deferred to agent files.
- BRANCH NAMING: added Legacy `NWAP/` prefix handling subsection. NWAP/ historical references preserved as record only; all NEW work uses WARP/ exclusively; new NWAP/ branch today = drift.
- Header version bumped 2.5 → 2.6, Last Updated set to 2026-05-03 18:30 Asia/Jakarta.

### CLAUDE.md (2.4 → 2.6, skipping 2.5 to align with AGENTS+COMMANDER)
- 4 missing v2.5-era authoritative rule sections mirrored from AGENTS.md:
  1. CHANGELOG RULE — append-only log format, one entry per lane closure.
  2. WORKTODO RULE — surgical edit only, check `[x]` only items completed by current task.
  3. SURGICAL EDIT RULE (ALL STATE FILES) — read full file before write, no regenerate from memory.
  4. STATE FILE SYNC RULE — PROJECT_STATE / ROADMAP / WORKTODO must stay in sync, drift detection trigger.
- 2 defer-pointer sections added:
  - PROJECT AWARENESS — short section deferring to AGENTS.md authoritative version.
  - AGENT IDENTITY VERIFICATION — short section deferring to AGENTS.md authoritative version.
- HARD RULES (ALL ROLES): added `Encoding: see AGENTS.md ENCODING RULE (UTF-8 without BOM)` line.
- PR Size & Pagination Protocol restructured:
  - Universal PR Split Rule removed (now lives in AGENTS.md PR SIZE RULE).
  - getPRFiles Pagination Rule kept (Claude Code-specific tooling).
  - Section title renamed to `getPRFiles Pagination Protocol (Claude Code specific)`.
  - Top-of-section note added: PR Split Rule reference points to AGENTS.md universal rule.
- Header version bumped 2.4 → 2.6, Last Updated set to 2026-05-03 18:30 Asia/Jakarta.

### COMMANDER.md (2.5 → 2.6)
- New rule added: PROJECT CONTEXT IN TASKS (AUTHORITATIVE) — placed after WARP🔹CMD INTERACTION RULES (after `aturan sistem lain` cross-reference). `Project:` and `Repo path:` fields recommended on every task. Single-active project: tag is RECOMMENDED but NOT required (matches AGENTS.md PROJECT AWARENESS RULE: "1 project active → no tag required"); agent resolves from registry default and does NOT reject. Multi-active project: tag is MANDATORY; agent rejects task without `Project:`. AGENTS.md is authoritative on conflict per RULE PRIORITY.
- 3 task templates updated (FORGE / SENTINEL / ECHO):
  - `Project: [name from PROJECT_REGISTRY.md]` field added after `Repo:` line.
  - `Repo path: {PROJECT_ROOT}` field added after `Project:` line.
  - All existing fields and structure preserved verbatim.
  - No content changes to OBJECTIVE / SCOPE / VALIDATION / DELIVERABLES / DONE CRITERIA / NEXT GATE.
- REFERENCE READING ORDER (BEFORE EVERY TASK): cross-reference note added — PROJECT AWARENESS RULE, AGENT IDENTITY VERIFICATION, and ESCALATION MATRIX are codified as authoritative in AGENTS.md.
- Header version bumped 2.5 → 2.6, Last Updated set to 2026-05-03 18:30 Asia/Jakarta.

---

## 2. Files modified (full repo-root paths)

- `AGENTS.md`
- `CLAUDE.md`
- `COMMANDER.md`
- `projects/polymarket/polyquantbot/reports/forge/governance-docs-sync.md` (new — this report)
- `projects/polymarket/polyquantbot/state/PROJECT_STATE.md`
- `projects/polymarket/polyquantbot/state/CHANGELOG.md`

---

## 3. Validation declaration

- **Validation Tier:** MINOR
- **Claim Level:** FOUNDATION
- **Validation Target:** Governance docs cross-file consistency, no contradictions introduced, version sync (all 3 docs at 2.6 with same Last Updated), all new sections well-formed, COMMANDER.md path corrected throughout AGENTS.md.
- **Not in Scope:** Runtime behavior, code, tests, state file rule semantics, hardcoded `polyquantbot` path replacement (deferred to a separate v3 migration lane), PROJECT_REGISTRY.md edits, operational truth changes to PROJECT_STATE.md / ROADMAP.md / WORKTODO.md beyond Last Updated bump and lane closure entry, cross-file rewording for style.
- **Suggested Next:** WARP🔹CMD review only (MINOR tier — WARP•SENTINEL not allowed). Post-merge sync per AGENTS.md POST-MERGE SYNC RULE.
