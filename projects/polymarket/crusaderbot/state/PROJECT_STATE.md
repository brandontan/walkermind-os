Last Updated : 2026-05-05 11:36
Status       : R12c exit watcher merged + SENTINEL APPROVED 95/100 (PR #865 + #866). R12a CI/CD pipeline PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — STANDARD tier, awaiting WARP🔹CMD review. Next: R12d Live Opt-In Checklist. Paper-default.

[COMPLETED]
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #861 — chore(crusaderbot): ROADMAP R12b drift fix + WORKTODO init (STANDARD, merged)
- R12a — CI/CD Pipeline (GitHub Actions) — PR #855 merged + gate-ratified (STANDARD)
- R12c — Auto-Close / Take-Profit — PR #865 merged, SENTINEL APPROVED 95/100 PR #866 (MAJOR)
- PR #867 — GATE post-merge sync safety rules (COMMANDER.md) — MINOR, merged

[IN PROGRESS]
- None

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- WARP🔹CMD: open R12d Live Opt-In Checklist lane (MAJOR — next gate before EXE path).

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) to avoid pulling a websockets dep — surfaces DNS/SSL/firewall outages; full handshake is a follow-up
