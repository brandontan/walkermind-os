# WARP•FORGE Report — commander-github-issue-rules

**Branch:** `WARP/commander-github-issue-rules`
**Date:** 2026-05-01 03:38 Asia/Jakarta
**Validation Tier:** MINOR
**Claim Level:** FOUNDATION
**Validation Target:** COMMANDER.md — 3 surgical insertions, header metadata update
**Not in Scope:** AGENTS.md, CLAUDE.md, all other files, any logic change

---

## 1. What was built

Three surgical insertions and one metadata bump applied to `COMMANDER.md`:

1. New top-level section `## GITHUB ISSUE AUTO-CREATE RULE` inserted between `## PR COMMENT AUTO-POST RULE` and `## AUTO PR ACTION RULE`. Defines when WARP🔹CMD must auto-create GitHub issues for STANDARD / MAJOR tasks, required labels, issue body format, auto-close behavior on PR merge, commit message format per role, and operational rules.
2. Two new bullets appended inside `## PR COMMENT AUTO-POST RULE` -> `### Rules` after the existing line `- If merging directly -> no comment needed, execute merge`:
   - `MINOR fix tasks: post PR comment only — no GitHub Issue created`
   - `Fix tasks reclassified to STANDARD or MAJOR mid-review: create GitHub Issue AND post PR comment with issue reference`
3. New `Issue   : #{github_issue_number}` line + 3 inline guidance markers inserted in `## WARP•FORGE TASK TEMPLATE` directly after `Env       : dev / staging / prod`.
4. Header metadata bumped: `Version: 2.4 -> 2.5`, `Last Updated: 2026-04-29 13:44 Asia/Jakarta -> 2026-05-01 03:38 Asia/Jakarta`.

No other content in `COMMANDER.md` was disturbed. No other files were touched.

## 2. Files created / modified

- Modified: `COMMANDER.md`
- Created: `projects/polymarket/polyquantbot/reports/forge/commander-github-issue-rules.md`
- Modified: `projects/polymarket/polyquantbot/state/PROJECT_STATE.md`

## 3. What is next

WARP🔹CMD review — Tier MINOR, no SENTINEL gate required. After merge, future WARP🔹CMD task generation must follow the new GITHUB ISSUE AUTO-CREATE RULE for STANDARD / MAJOR tasks and include the `Issue:` field in WARP•FORGE task bodies.
