# CrusaderBot -- Fast Track Roadmap

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-11 23:15 Asia/Jakarta

## Current Posture

- Production: LIVE on Fly.io (PAPER ONLY)
- Telegram UX Phase 5A-5J complete
- Real CLOB Phase 4A-4E complete; live path guarded
- Week 1 Fast Track Tracks A-E merged
- Week 2 first lane Premium PNL Insights UX merged via PR #965
- Activation guards: OFF / NOT SET (do not touch)
- Roadmap Mode: FAST TRACK (Mr. Walker decision)

## Week 1 -- Core Trading Loop (COMPLETE)

| Track | Scope | Tier | Status | Notes |
|---|---|---|---|---|
| A | Trade Engine + TP/SL worker | MAJOR | ✅ MERGED | MERGED PR #942 (2026-05-11). TradeEngine FULL RUNTIME INTEGRATION; signal_scan_job routes through TradeEngine; 47 tests green |
| B | Copy Trade Execution | MAJOR | ✅ MERGED | MERGED PR #948 (2026-05-11). CopyTradeMonitor wired through TradeEngine; 25 tests green |
| C | Trade Notifications | STANDARD | ✅ MERGED | MERGED PR #951 (2026-05-11). TradeNotifier service layer; ENTRY/TP_HIT/SL_HIT/MANUAL/EMERGENCY/COPY_TRADE scaffold; paper.py wired; 16 tests green |
| D | Live Gate Hardening | MAJOR | ✅ MERGED | MERGED PR #954 (2026-05-11). Slippage/market-impact gate step 14, risk assertion audit, parity hooks, readiness validator; WARP-SENTINEL APPROVED 92/100; 35 tests green |
| E | Daily P&L Report | STANDARD | ✅ MERGED | MERGED PR #962 (2026-05-11). Paper-mode daily Telegram P&L summary; opened/closed/W/L counts; no-trade empty state; scheduler callback wiring; 26 daily_pnl_summary tests green; issue #960 closed |

**During Week 1:**

- No live trading
- No guard flips
- PAPER only
- SENTINEL required for MAJOR lanes

## Week 2 -- Live Gate + Premium UX

| Lane | Scope | Tier | Status | Notes |
|---|---|---|---|---|
| 1 | Premium PNL Insights UX | STANDARD | ✅ MERGED | MERGED PR #965 (2026-05-11). /insights, insights:refresh, dashboard:insights, insights_kb, dashboard + my_trades nav updates, paper-mode query boundary, _safe_md, signed PNL formatting; 22 tests green; issue #963 closed; PR #964 superseded and closed unmerged |
| 2 | Live Gate Preparation | MAJOR | ⏳ NEXT | SENTINEL + owner checklist required. PAPER ONLY. No activation guard flips |
| 3 | Charts / insights follow-on | STANDARD | ⏳ QUEUED | Follow-on premium UX. Must remain presentation-only unless re-scoped |
| 4 | Referral / share / fee prep | STANDARD | ⏳ QUEUED | Prep lane only; no activation guard changes |

## Week 3 -- Multi-User Hardening

- Tenant isolation audit
- Access tiers + admin controls
- Onboarding polish + conversion flows

## Week 4 -- Closed Beta

- Runtime observation
- Paper trading stability
- Performance validation
- No new feature lanes planned

## Non-Negotiable Rules

- ENABLE_LIVE_TRADING = false / NOT SET
- EXECUTION_PATH_VALIDATED = false / NOT SET
- CAPITAL_MODE_CONFIRMED = false / NOT SET
- RISK_CONTROLS_VALIDATED = false / NOT SET
- USE_REAL_CLOB = false / NOT SET
- Paper mode only until explicit owner decision
