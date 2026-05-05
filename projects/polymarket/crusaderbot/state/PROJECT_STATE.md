Last Updated : 2026-05-05 14:54
Status       : R12e auto-redeem merged (PR #869, SENTINEL APPROVED 94/100). R12a CI/CD pipeline PR open. R12c exit watcher PR open (MAJOR, SENTINEL audit required). R12d Telegram position UX merged (PR #868). Paper-default.

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
- R12d — Telegram Position UX — PR #868 MERGED (STANDARD, NARROW INTEGRATION)
- R12e — Auto-Redeem System — PR #869 MERGED (MAJOR, SENTINEL APPROVED 94/100)

[IN PROGRESS]
- R12a — CI/CD Pipeline (GitHub Actions) — PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review
- R12c — Auto-Close / Take-Profit — PR open: WARP/CRUSADERBOT-R12C-EXIT-WATCHER — MAJOR tier, SENTINEL audit required before merge

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- WARP•SENTINEL validation required for R12c exit watcher before merge. Source: projects/polymarket/crusaderbot/reports/forge/r12c-exit-watcher.md. Tier: MAJOR. Branch: WARP/CRUSADERBOT-R12C-EXIT-WATCHER.
- WARP🔹CMD review required for R12a CI/CD pipeline. Source: projects/polymarket/crusaderbot/reports/forge/r12a-cicd-pipeline.md. Tier: STANDARD. Branch: WARP/CRUSADERBOT-R12A-CICD-PIPELINE.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) to avoid pulling a websockets dep — surfaces DNS/SSL/firewall outages; full handshake is a follow-up
