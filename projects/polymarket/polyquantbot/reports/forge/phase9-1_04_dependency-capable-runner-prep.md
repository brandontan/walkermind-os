# Phase 9.1 — Dependency-Capable Runner Preparation

**Date:** 2026-04-20 19:21
**Branch:** feature/prepare-phase-9-1-dependency-capable-runner
**Task:** Prepare reproducible dependency-capable runner requirements for Phase 9.1 canonical runtime-proof closure lane

## 1. What was built

- Added a dedicated runner-preparation guide at `projects/polymarket/polyquantbot/docs/phase9_1_dependency_capable_runner_prep.md` documenting exact requirements for package-index reachability, dependency install success, `py_compile` success, and scoped pytest success.
- Updated `projects/polymarket/polyquantbot/docs/public_paper_beta_spine.md` so dependency-complete runtime-proof command/path references align with the canonical Phase 9.1 lane.
- Preserved canonical runtime-proof command unchanged:
  - `python -m projects.polymarket.polyquantbot.scripts.run_phase9_1_runtime_proof`
- Did not rerun canonical runtime proof and did not refresh canonical evidence artifacts.

## 2. Current system architecture (relevant slice)

Phase 9.1 closure flow remains:
1. operator executes canonical package command from repo root
2. runner creates isolated venv and installs dependency-complete runtime/test stack
3. runner executes `py_compile` against scoped target manifest
4. runner executes scoped pytest targets
5. runner writes canonical evidence log

This task adds explicit environment/runner prerequisites so the same unchanged command can be rerun in a dependency-capable environment.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/polyquantbot/docs/phase9_1_dependency_capable_runner_prep.md`
- `projects/polymarket/polyquantbot/docs/public_paper_beta_spine.md`
- `projects/polymarket/polyquantbot/reports/forge/phase9-1_04_dependency-capable-runner-prep.md`
- `PROJECT_STATE.md`

## 4. What is working

- Reproducible runner prerequisites are now explicitly documented for:
  - package-index reachability
  - dependency install success
  - `py_compile` success
  - scoped pytest success
- Canonical Phase 9.1 runtime-proof command remains unchanged and is clearly called out as the authoritative execution path.
- No new rerun evidence artifact and no blocked-rerun continuity artifact were produced in this task.

## 5. Known issues

- Current Codex runner still cannot prove dependency-complete closure because package-index access constraints remain environment-dependent.
- Phase 9.1 closure status therefore remains pending real execution in a dependency-capable runner.

## 6. What is next

- COMMANDER review this preparation lane.
- After merge, execute the canonical command in a dependency-capable runner to capture successful install + `py_compile` + scoped pytest evidence in the canonical log.

Validation Tier   : STANDARD
Claim Level       : FOUNDATION
Validation Target : reproducible dependency-capable runner requirements and documentation for canonical Phase 9.1 runtime-proof lane
Not in Scope      : canonical rerun execution, evidence log refresh, blocked-rerun continuity artifacts, runtime behavior changes, Phase 9.2 implementation
Suggested Next    : COMMANDER review
