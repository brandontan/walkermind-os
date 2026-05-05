Last Updated : 2026-05-05 08:14
Status       : CRUSADERBOT-STATE-FIX merged (PR #861) — ROADMAP R12b corrected, WORKTODO.md initialized, state files synced. R12a CI/CD pipeline PR open (WARP/CRUSADERBOT-R12A-CICD-PIPELINE). Paper-default.

[COMPLETED]
- PR #852 — feat(crusaderbot): import full Replit build R1-R11
- PR #853 — sentinel: crusaderbot-replit-import PASS (post-fix)
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #857 — chore(crusaderbot): state sync — PR #856 post-merge (WARP•ECHO routine)
- PR #858 — chore(crusaderbot): state sync — PR #857 post-merge (WARP•ECHO routine)
- PR #861 — chore(crusaderbot): state sync — ROADMAP R12b drift fix + WORKTODO init (WARP/CRUSADERBOT-STATE-FIX merged)

[IN PROGRESS]
- R12a — CI/CD Pipeline (GitHub Actions) — PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review

[NOT STARTED]
- R12c — Auto-Close / Take-Profit (MAJOR — execution path)
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- WARP🔹CMD review of R12a PR (STANDARD, no SENTINEL required). Source: projects/polymarket/crusaderbot/reports/forge/r12a-cicd-pipeline.md

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) to avoid pulling a websockets dep — surfaces DNS/SSL/firewall outages; full handshake is a follow-up
