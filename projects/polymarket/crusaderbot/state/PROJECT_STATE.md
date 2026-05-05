Last Updated : 2026-05-05 19:15 UTC
Status       : R12e auto-redeem SENTINEL audit complete: APPROVED 94/100, 0 critical, OBS-01 resolved PASS. PR #869 cleared for WARP🔹CMD final merge decision. R12d Telegram position UX PR still open: WARP/CRUSADERBOT-R12D-TELEGRAM-POSITION-UX. R12c exit watcher PR still open: WARP/CRUSADERBOT-R12C-EXIT-WATCHER — MAJOR tier, SENTINEL audit required. R12a CI/CD pipeline PR still open. Paper-default.

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

[IN PROGRESS]
- R12a — CI/CD Pipeline (GitHub Actions) — PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review
- R12c — Auto-Close / Take-Profit — PR open: WARP/CRUSADERBOT-R12C-EXIT-WATCHER — MAJOR tier, SENTINEL audit required before merge
- R12d — Telegram Position UX (live position monitor + per-position force close) — PR #868 MERGED (4f5e12201964) — STANDARD tier
- R12e — Auto-Redeem System (instant + hourly workers + redeem_queue + Settings UI) — PR open: WARP/CRUSADERBOT-R12E-AUTO-REDEEM — MAJOR tier, SENTINEL audit required before merge

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- WARP🔹CMD final merge decision required for R12e auto-redeem. SENTINEL APPROVED 94/100, 0 critical. Source: projects/polymarket/crusaderbot/reports/sentinel/r12e-auto-redeem.md. Tier: MAJOR. Branch: WARP/CRUSADERBOT-R12E-AUTO-REDEEM.
- WARP•SENTINEL validation required for R12c exit watcher before merge. Source: projects/polymarket/crusaderbot/reports/forge/r12c-exit-watcher.md. Tier: MAJOR. Branch: WARP/CRUSADERBOT-R12C-EXIT-WATCHER.
- WARP🔹CMD review required for R12d Telegram position UX. Source: projects/polymarket/crusaderbot/reports/forge/r12d-telegram-position-ux.md. Tier: STANDARD. Branch: WARP/CRUSADERBOT-R12D-TELEGRAM-POSITION-UX.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) to avoid pulling a websockets dep — surfaces DNS/SSL/firewall outages; full handshake is a follow-up
