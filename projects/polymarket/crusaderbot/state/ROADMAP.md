# CrusaderBot — Fast Track Roadmap

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-11 10:30

## Current Posture

- Production: LIVE on Fly.io (PAPER ONLY)
- Telegram UX Phase 5A-5I complete
- Real CLOB Phase 4A-4E complete; live path guarded
- Fast Track Track A MERGED PR #942; TradeEngine active in scan runtime
- Activation guards: OFF (do not touch)
- Roadmap Mode: FAST TRACK (Mr. Walker decision)

## Week 1 — Core Trading Loop (ACTIVE)

| Track | Scope | Tier | Status | Notes |
|---|---|---|---|--|
| A | Trade Engine + TP/SL worker | MAJOR | ✅ MERGED | PR #942 (2026-05-11); TradeEngine wired into signal_scan_job; 47 tests green |
| B | Copy Trade Execution | MAJOR | ❌ QUEUED | Unblocked; MAJOR, SENTINEL required; branch to be declared by WARP🔹CMD |
| C | Trade Notifications | STANDARD | ❌ QUEUED | Unblocked; entry / exit / copy trade Telegram notifications |
| D | Risk Caps + Kill Switch hardening | MAJOR | ❌ QUEUED | Hard exposure caps, daily loss, max open positions, kill switch |
| E | Daily P&L Report | STANDARD | ❌ QUEUED | Scheduled daily summary in Telegram |

**During Week 1:**
- No live trading
- No guard flips
- PAPER only
- SENTINEL required for MAJOR lanes

## Week 2 – Live Gate + Premium UX

- Live gate preparation (SENTINEL + owner checklist)
- UB improvements: charts, insights, better PNL surfaces
- Referral / fee /share prep

## Week 3 — Multi-User Hardening

- Tenant isolation audit
- Access tiers + admin controls
- Onboarding polish + conversion flows

## Week 4 – Closed Beta

- Runtime observation
- Paper trading stability
- Performance validation
- No new feature lanes planned

## Non-Negotiable Rules

- ENABLE_LIVE_TRADING = false
- EXECUTION_PATH_VALIDATED = false
- CAPITAL_MODE_CONFIRMED = false
- USE_REAL_CLOB = false
- Paper mode only until explicit owner decision
