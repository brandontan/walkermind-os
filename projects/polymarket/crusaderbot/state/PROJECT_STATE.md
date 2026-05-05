Last Updated : 2026-05-05 11:15
Status       : R12c exit watcher MERGED and SENTINEL APPROVED (PR #865 + PR #866, 95/100). R12a CI/CD pipeline PR still open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE. Paper-default.

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
- R12c — Auto-Close / Take-Profit — MERGED (PR #865) + SENTINEL APPROVED 95/100 (PR #866)

[IN PROGRESS]
- R12a — CI/CD Pipeline (GitHub Actions) — PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- WARP🔹CMD review required for R12a CI/CD Pipeline. Source: projects/polymarket/crusaderbot/reports/forge/r12a-cicd-pipeline.md. Tier: STANDARD. Branch: WARP/CRUSADERBOT-R12A-CICD-PIPELINE.
- Post-merge state sync for PR #865 + PR #866 (R12c closed). ROADMAP.md R12c row should be updated to Done.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) to avoid pulling a websockets dep — surfaces DNS/SSL/firewall outages; full handshake is a follow-up
