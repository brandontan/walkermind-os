# CrusaderBot — Fast Track Roadmap

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-11 16:25

## Current Posture

- Production: LIVE on Fly.io (PAPer ONLY)
- Telegram UX Phase 5A-5I complete
- Real CLOB Phase 4A-4E complete; live path guarded
- Activation guards: OFF (do not touch)
- Roadmap Mode: FAST TRACK (Mr. Walker decision)

## Week 1 — Core Trading Loop (ACTIVE)

| Track | Scope | Tier | Status | Notes |
|---|---|---|---|--|
| A | Trade Engine + TP/SL worker | MAJOR | ✅ MERGED | MERGED PR #942 (2026-05-11). TradeEngine FULL RUNTIME INTEGRATION; signal_scan_job routes through TradeEngine; 47 tests green |
| B | Copy Trade Execution | MAJOR | ✅ MERGED | MERGED PR #948 (2026-05-11). CopyTradeMonitor wired through TradeEngine; 23 tests green |
| C | Trade Notifications | STANDARD | ✅ MERGED | MERGED PR #951 (2026-05-11). TradeNotifier service layer; 16 tests green |
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
