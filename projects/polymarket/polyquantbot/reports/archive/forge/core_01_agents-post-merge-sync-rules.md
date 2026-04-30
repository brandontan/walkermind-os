# Forge Report — AGENTS.md Post-Merge Sync Rule Insertions

## 1. What Was Changed

Three targeted insertions made to AGENTS.md (repo root). No existing content was modified or removed.

**Insertion 1 — FAILURE CONDITIONS (GLOBAL)**
Added three new failure conditions immediately after the `project-local PROJECT_STATE.md exists alongside repo-root version` bullet:
- COMMANDER merged a PR but did not sync PROJECT_STATE.md to reflect merged state
- COMMANDER merged a PR but did not sync ROADMAP.md when roadmap-level truth changed
- COMMANDER proceeded to the next build task before post-merge sync was completed

**Insertion 2 — POST-MERGE SYNC RULE (COMMANDER — MANDATORY)**
Added new section immediately after the existing `## POST-MERGE SYNC RULE` section (before `## REPORT ARCHIVE RULE`). Section defines COMMANDER ownership of post-merge truth, post-merge checklist, update triggers for PROJECT_STATE.md and ROADMAP.md, and the hard rule that next build task must not be opened until sync is verified complete.

Note: task declared anchor was `## PLATFORM COMPLIANCE (ALL ENVIRONMENTS)` which does not exist in AGENTS.md. COMMANDER confirmed placement after existing `## POST-MERGE SYNC RULE` section.

**Insertion 3 — FORGE-X pre-flight MAJOR checklist**
Added one line immediately after `[ ] Max 5 files per commit preferred; split if needed` in the MAJOR adds block:
- `[ ] ROADMAP.md updated if roadmap-level truth changed (active phase, milestone, task status)`

## 2. Files Modified

- `AGENTS.md`

## 3. Validation Declaration

Validation Tier   : MINOR
Claim Level       : FOUNDATION
Validation Target : AGENTS.md three new insertions only
Not in Scope      : any other file, any existing AGENTS.md content, runtime behavior
Suggested Next    : COMMANDER review
