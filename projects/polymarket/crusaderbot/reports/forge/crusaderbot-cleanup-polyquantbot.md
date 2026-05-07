# WARP•FORGE Report — CrusaderBot Cleanup: Remove Legacy polyquantbot Directory

Lane: `WARP/CRUSADERBOT-CLEANUP-POLYQUANTBOT`
Date: 2026-05-07 12:52 Asia/Jakarta
Issue: #890

---

## 1. What was changed

Removed all active references to the legacy `projects/polymarket/polyquantbot/` tree and deleted
the directory from the repository. The polyquantbot project was marked DORMANT in
PROJECT_REGISTRY.md after CrusaderBot took over as the active project. This lane closes the
cleanup debt by:

- Deleting `projects/polymarket/polyquantbot/` entirely (the full legacy project directory)
- Deleting `.github/workflows/phase9_1_runtime_proof.yml` (CI workflow with hardcoded polyquantbot
  paths — the only hard CI blocker found in pre-flight)
- Deleting `.ona/automations.yaml` (deprecated Ona agent automation config — Ona removed 2026-05-05)
- Updating 5 doc files with stale `polyquantbot` path references → `crusaderbot`

Pre-flight grep (run before any deletion) confirmed the hard blocker in
`.github/workflows/phase9_1_runtime_proof.yml`. All declared scope completed.

Out-of-scope references not touched (noted for follow-up):
- `main.py` (repo root) — legacy Railway entrypoint importing polyquantbot; dead code, no CrusaderBot CI impact
- `pytest.ini` (repo root) — testpaths pointing to polyquantbot/tests; not read by CrusaderBot CI
- `CURSOR.md`, `ONA.md` — old persona/context files
- `.github/agents/AGENTS_FINAL_MERGED.md`, `.github/agents/briefer.agent.md`,
  `.github/agents/sentinel.agent.md`, `.github/agents/forge-x.agent.md` — deprecated agent files
- `.github/copilot_instructions.md`, `.github/ISSUE_TEMPLATE/warp-task.yml` — GitHub tooling
- `docs/system_specs.md`, `docs/workflow_and_execution_model.md` — legacy docs
- `.agents/skills/polymarket-bot/` — skill files
- `replit.md` — Replit environment doc
- Historical forge reports in `projects/polymarket/crusaderbot/reports/forge/` and
  `projects/app/walker_devops/reports/forge/` — historical records, must not be modified

---

## 2. Files created / modified (full repo-root paths)

**Deleted:**
- `.github/workflows/phase9_1_runtime_proof.yml`
- `.ona/automations.yaml`
- `projects/polymarket/polyquantbot/` (entire directory — all files removed)

**Updated:**
- `PROJECT_REGISTRY.md` — removed DORMANT polyquantbot row (line 10)
- `README.md` — updated active project path (line 27) and repo tree (line 79)
- `AGENTS.md` — updated 7 polyquantbot path/example references → crusaderbot
  (lines 326, 391, 545, 906, 1112–1113; policy sections untouched)
- `COMMANDER.md` — updated 2 references (line 319 WORKTODO path, line 636 PROJECT_ROOT footer)
- `CLAUDE.md` — updated 3 references (line 88 PROJECT_ROOT block, lines 429–430 path examples)

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-cleanup-polyquantbot.md` (this file)

---

## 3. Validation metadata

Validation Tier   : MINOR
Claim Level       : NONE — pure cleanup, zero behavioral change
Validation Target : Pre-flight grep confirms zero active polyquantbot references in all
                    declared scope files after changes applied. CrusaderBot CI unaffected
                    (runs from projects/polymarket/crusaderbot/ working directory).
Not in Scope      : main.py (repo root), pytest.ini (repo root), CURSOR.md, ONA.md,
                    .github/agents/* deprecated files, .github/copilot_instructions.md,
                    .github/ISSUE_TEMPLATE/warp-task.yml, docs/system_specs.md,
                    docs/workflow_and_execution_model.md, .agents/skills/polymarket-bot/*,
                    replit.md, historical forge reports in crusaderbot/ and walker_devops/,
                    docs/blueprint/crusaderbot.md (intentional historical note per WARP🔹CMD)
Suggested Next    : WARP🔹CMD auto-review + merge. No SENTINEL required (MINOR tier).
                    Follow-up MINOR lane recommended for out-of-scope reference cleanup.
