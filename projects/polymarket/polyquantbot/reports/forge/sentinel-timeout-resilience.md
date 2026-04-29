# WARP•FORGE Report: sentinel-timeout-resilience

Branch: WARP/sentinel-timeout-resilience
Date: 2026-04-29 07:24

---

## 1. What was changed

Four surgical rule additions across CLAUDE.md and AGENTS.md to address
WARP•SENTINEL stream idle timeout failure pattern.

- CLAUDE.md — Timeout Handling section: added SENTINEL report split rule
  (2 write calls: sections 1-5, then 6-end) and a new
  "On Stream Timeout Recovery (SENTINEL)" block covering resume behavior.
- CLAUDE.md — Task Chunking / Timeout Prevention Rules: added SENTINEL
  report 150-line-per-call limit bullet.
- AGENTS.md — Task Chunking / Timeout Prevention Rules: mirrored the same
  150-line-per-call bullet.
- AGENTS.md — ROLE: WARP•SENTINEL / after Anti-loop rule: added new
  "Stream timeout recovery" section with 6 recovery rules including
  anti-loop count behavior.

No files created. No surrounding content rewritten. str_replace only.
Version numbers in both files left unchanged.

---

## 2. Files modified

- CLAUDE.md (repo root)
- AGENTS.md (repo root)

---

## 3. Validation

Validation Tier  : MINOR
Claim Level      : FOUNDATION
Validation Target: Rule text added correctly to 4 sections across 2 files
Not in Scope     : Runtime behavior, actual sentinel execution, report format,
                   COMMANDER.md, templates
Suggested Next   : WARP🔹CMD review only (Tier = MINOR)
