Last Updated : 2026-05-05 11:15
Status       : R12c exit watcher merged (PR #865) — TP/SL/force-close per-position auto-close + applied_* snapshot immutability + retry-once-on-CLOB-error. R12a CI/CD pipeline PR still open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE awaiting WARP🔹CMD review. Paper-default.

[COMPLETED]
- PR #852 — feat(crusaderbot): import full Replit build R1-R11
- PR #853 — sentinel: crusaderbot-replit-import PASS (post-fix)
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #857 — chore(crusaderbot): state sync — PR #856 post-merge (WARP•ECHO routine)
- PR #858 — chore(crusaderbot): state sync — PR #857 post-merge (WARP•ECHO routine)
- PR #860 — chore(crusaderbot): state sync — PR #858 post-merge (WARP•ECHO routine)
- PR #861 — chore(crusaderbot): ROADMAP R12b drift fix + WORKTODO init (STANDARD, merged)
- PR #865 — feat(crusaderbot): R12c exit watcher — TP/SL/force-close auto-close + applied_* snapshot (MAJOR, merged)

[IN PROGRESS]
- R12a — CI/CD Pipeline (GitHub Actions) — PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- WARP🔹CMD review required for R12a CI/CD pipeline PR (WARP/CRUSADERBOT-R12A-CICD-PIPELINE). Tier: STANDARD.
- After R12a merges: open R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE).

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) to avoid pulling a websockets dep — surfaces DNS/SSL/firewall outages; full handshake is a follow-up
