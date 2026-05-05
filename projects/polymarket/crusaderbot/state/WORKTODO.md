# CrusaderBot — WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-05 18:30 UTC

---

## Right Now

Active lane: WARP/CRUSADERBOT-R12E-AUTO-REDEEM — MAJOR tier, SENTINEL audit pending.
Next: WARP•SENTINEL MAJOR audit of R12e auto-redeem + R12c exit watcher (PR #865). R12a CI/CD PR awaiting WARP🔹CMD review.

---

## R12 — Production Readiness

- [x] R12b — Fly.io Health Alerts — Done (PR #856 merged)
- [ ] R12a — CI/CD Pipeline (GitHub Actions) — IN PROGRESS: WARP/CRUSADERBOT-R12A-CICD-PIPELINE open, awaiting WARP🔹CMD review
- [ ] R12c — Auto-Close / Take-Profit — IN PROGRESS: WARP/CRUSADERBOT-R12C-EXIT-WATCHER open, MAJOR — SENTINEL audit required
- [x] R12d — Telegram Position UX — DONE (PR #868 merged 4f5e12201964) (live position monitor + per-position force close) — IN PROGRESS: WARP/CRUSADERBOT-R12D-TELEGRAM-POSITION-UX open, STANDARD — awaiting WARP🔹CMD review
- [ ] R12d — Live Opt-In Checklist — NOT STARTED (MAJOR — hard gate before EXE)
- [ ] R12e — Auto-Redeem System — IN PROGRESS: WARP/CRUSADERBOT-R12E-AUTO-REDEEM open, MAJOR — SENTINEL audit required (services/redeem instant+hourly workers + redeem_queue + Settings UI)
- [ ] R12e — Live → Paper Auto-Fallback — NOT STARTED (MAJOR)
- [ ] R12f — Daily P&L Summary — NOT STARTED (STANDARD)
- [ ] R12 — Deployment (Fly.io) final — NOT STARTED (MAJOR — blocked on R12a-R12f all merged)

Done condition: All R12a-R12f merged + activation guards reviewed by WARP🔹CMD before final R12 deployment.

---

## Activation Guards

- [ ] EXECUTION_PATH_VALIDATED — NOT SET (Engineering gate — R12c-R12e required first)
- [ ] CAPITAL_MODE_CONFIRMED — NOT SET (Operator gate)
- [ ] ENABLE_LIVE_TRADING — NOT SET (Owner gate — final activation)
- [ ] RISK_CONTROLS_VALIDATED — NOT SET (SENTINEL gate — R7/R8/R9 live re-audit)
- [ ] SECURITY_HARDENING_VALIDATED — NOT SET (SENTINEL gate)
- [ ] FEE_COLLECTION_ENABLED — NOT SET (Owner gate — R11 reviewed)
- [ ] AUTO_REDEEM_ENABLED — NOT SET (Engineering gate — R10 reviewed)

Done condition: All guards SET only after WARP🔹CMD + SENTINEL + Owner approval per ROADMAP.md.

---

## Known Issues (deferred)

- [ ] /deposit no tier gate (intentional, non-blocking)
- [ ] services/* dead code (LOW — post-R12 cleanup)
- [ ] check_alchemy_ws is TCP-only, not full WS handshake (follow-up lane)
- [ ] F401 unused imports in bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py (ruff baseline E9/F63/F7/F82 only — dedicated cleanup lane needed)
