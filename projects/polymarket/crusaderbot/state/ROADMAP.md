# CrusaderBot — Fast Track Roadmap

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-11 21:30 Asia/Jakarta

## Current Posture

- Production: LIVE on Fly.io (PAPER ONLY)
- Telegram UX Phase 5A-5I complete
- Real CLOB Phase 4A-4E complete; live path guarded
- Activation guards: OFF (do not touch)
- Roadmap Mode: FAST TRACK (Mr. Walker decision)

## Week 1 — Core Trading Loop (COMPLETE)

| Track | Scope | Tier | Status | Notes |
|---|---|---|---|
---|
| A | Trade Engine + TP/SL worker | MAJOR | ✅ MERGED | MERGED PR #942 (2026-05-11). TradeEngine FULL RUNTIME INTEGRATION; signal_scan_job routes through TradeEngine; 47 tests green |
| B | Copy Trade Execution | MAJOR | ✅ MERGED | MERGED PR #948 (2026-05-11). CopyTradeMonitor wired through TradeEngine; 25 tests green |
| C | Trade Notifications | STANDARD | ✅ MERGED | MERGED PR #951 (2026-05-11). TradeNotifier service layer; ENTRY/TP_HIT/SL_HIT/MANUAL/EMERGENCY/COPY_TRADE scaffold; paper.py wired; 16 tests green |
| D | Risk Caps + Kill Switch hardening | MAJOR | ✅ MERGED | MERGED PR #954 (2026-05-11). Slippage gate step 14, risk assertions, ReadinessValidator, parity hooks; SENTINEL APPROVED 92/100; 35 tests green |
| E | Daily P&L Report | STANDARD | ❌ QUEUED | Scheduled daily summary in Telegram |

**During Week 1:**

- No live trading
- No guard flips
- PAPER only
- SENTINEL required for MAJOR lanes

## Week 2 – Live Gate + Premium UX

- Live gate preparation (SENTINEL + owner checklist)
- UI improvements: charts, insights, better PNL surfaces
- Referral / fee / share prep

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
