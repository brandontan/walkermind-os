# WARP•FORGE REPORT: commander-pr-comment-rule

Branch    : WARP/commander-pr-comment-rule
Date      : 2026-04-29 08:07 Asia/Jakarta
Tier      : MINOR
Claim     : FOUNDATION

---

## 1. What was changed

Three updates to COMMANDER.md and one path-reference fix across AGENTS.md:

**COMMANDER.md — PR REVIEW FLOW (steps 5-7):**
Step 6 updated and step 7 added. When needs-fix or SENTINEL required, WARP🔹CMD must post a copy-ready task comment to the PR immediately. Merge/close actions continue to execute without stating intent.

**COMMANDER.md — PR COMMENT AUTO-POST RULE (new section):**
New section inserted between PR REVIEW FLOW and AUTO PR ACTION RULE. Defines trigger conditions, scope, comment formats (fix task and sentinel task), and posting rules. WARP🔹CMD must post a PR comment immediately after any review that requires fix or SENTINEL — no waiting for additional instruction.

**COMMANDER.md — WARP•FORGE TASK TEMPLATE Branch block:**
Four prohibition lines added below the existing three branch annotation lines. AUTO-GENERATE BRANCH IS FORBIDDEN. First action and verify step now explicit in the template.

**AGENTS.md — docs/COMMANDER.md path references:**
Five occurrences of `docs/COMMANDER.md` replaced with `COMMANDER.md` (lines 40, 219, 299, 378, 782). File lives at repo root, not under docs/.

---

## 2. Files modified (full repo-root paths)

- `COMMANDER.md` — PR REVIEW FLOW steps, PR COMMENT AUTO-POST RULE section, WARP•FORGE TASK TEMPLATE Branch block, Last Updated + Version
- `AGENTS.md` — five `docs/COMMANDER.md` path references corrected to `COMMANDER.md`

---

## 3. Validation

Validation Tier   : MINOR
Claim Level       : FOUNDATION
Validation Target : COMMANDER.md rule additions + branch prohibition warning + path reference corrections in AGENTS.md
Not in Scope      : Any runtime logic, state files, other docs, CLAUDE.md (no docs/COMMANDER.md refs found)
Suggested Next    : WARP🔹CMD review
