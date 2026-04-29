# sentinel-timeout-resilience

Branch: WARP/sentinel-timeout-resilience
Date: 2026-04-29 07:24 Asia/Jakarta

---

## 1. What was changed

Added the requested WARP•SENTINEL stream-timeout resilience rules as surgical text updates only.

- `CLAUDE.md` Timeout Handling now includes split-write guidance for WARP•SENTINEL reports, an intermediate-output rule after every 2 reads, and a dedicated stream-timeout recovery subsection.
- `CLAUDE.md` Task Chunking Protocol now limits WARP•SENTINEL report writes to 150 lines per call with a required two-call split and `CHUNK [N] COMPLETE` signal.
- `AGENTS.md` Task Chunking Protocol now mirrors the same WARP•SENTINEL report write limit and split-call rule.
- `AGENTS.md` ROLE: WARP•SENTINEL — VALIDATE now includes a stream-timeout recovery block directly after the anti-loop rule.

---

## 2. Files modified

- CLAUDE.md
- AGENTS.md
- projects/polymarket/polyquantbot/reports/forge/sentinel-timeout-resilience.md
- projects/polymarket/polyquantbot/state/PROJECT_STATE.md

---

## 3. Validation metadata

Validation Tier   : MINOR
Claim Level       : FOUNDATION
Validation Target : Rule text added correctly to the 4 requested sections across CLAUDE.md and AGENTS.md
Not in Scope      : COMMANDER.md, report templates, sentinel report structure, runtime behavior, actual sentinel execution, any file outside the scoped docs plus required forge report and PROJECT_STATE.md update
Suggested Next    : WARP🔹CMD review
