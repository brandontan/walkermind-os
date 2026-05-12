# CrusaderBot — Fast Track Roadmap

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-13 06:01 Asia/Jakarta

## Current Posture

- Production: LIVE on Fly.io (PAPER ONLY)
- Telegram UX Phase 5A-5J complete
- Real CLOB Phase 4A-4E complete; live path guarded
- Week 1 Fast Track Tracks A-E + Premium PNL Insights MERGED — Week 1 fully complete
- Activation guards: OFF (do not touch)
- Roadmap Mode: FAST TRACK (Mr. Walker decision)

## Week 1 — Core Trading Loop (COMPLETE)

| Track | Scope | Tier | Status | Notes |
|---|---|---|---|
|---|
| A | Trade Engine + TP/SL worker | MAJOR | ✅ MERGED | MERGED PR #942 (2026-05-11). TradeEngine FULL RUNTIME INTEGRATION; signal_scan_job routes through TradeEngine; 47 tests green |
| B | Copy Trade Execution | MAJOR | ✅ MERGED | MERGED PR #948 (2026-05-11). CopyTradeMonitor wired through TradeEngine; 25 tests green |
| C | Trade Notifications | STANDARD | ✅ MERGED | MERGED PR #951 (2026-05-11). TradeNotifier service layer; ENTRY/TP_HIT/SL_HIT/MANUAL/EMERGENCY/COPY_TRADE scaffold; paper.py wired; 16 tests green |
| D | Live Gate Hardening | MAJOR | ✅ MERGED | MERGED PR #954 (2026-05-11). Slippage/market-impact gate step 14, risk assertion audit, parity hooks, readiness validator; WARP•SENTINEL APPROVED 92/100; 35 tests green |
| E | Daily P&L Report | STANDARD | ✅ MERGED | MERGED PR #962 (2026-05-11). Paper-mode daily Telegram P&L summary; opened/closed/W/L counts; no-trade empty state; scheduler callback wiring; 26 daily_pnl_summary tests green; issue #960 closed |
| PNL | Premium PNL Insights UX | STANDARD | ✅ MERGED | MERGED PR #965 (2026-05-11). /insights command, insights_kb, dashboard:insights sub, my_trades nav update, mode=paper boundary, _safe_md title escaping, best_pnl sign fix; 22 tests green; issue #963 closed |

**During Week 1:**

- No live trading
- No guard flips
- PAPER only
- SENTINEL required for MAJOR lanes

## Week 2 – Live Gate + Premium UX — IN PROGRESS

| Track | Scope | Tier | Status | Notes |
|---|---|---|---|---|
| F | Live Opt-In Gate | MAJOR | ✅ MERGED | MERGED PR #970 (2026-05-11). 3-step /enable_live gate; 4-guard check; mode_change_events audit (021); auto-fallback 60s monitor; 20 hermetic tests green; issue #968 closed |
| G | UI Premium Pack 1 | STANDARD | ✅ MERGED | MERGED in prior lane; queue now clear (open PRs = 0). |

- Charts / insights follow-on (post-PNL-Insights)
- Referral / fee prep

## Week 3 — Multi-User Hardening

| Track | Scope | Tier | Status | Notes |
|---|---|---|---|---|
| J | Multi-User Isolation Audit | MAJOR | ✅ MERGED | MERGED PR #988 (2026-05-12). 120+ queries audited; zero isolation violations; 24 hermetic tests green; WARP•SENTINEL APPROVED 98/100 |

- Access tiers + admin controls (Track K — merged in prior lane; no open PR).
- Onboarding polish + conversion flows (Track L — merged in prior lane; no open PR).

## Week 4 – Closed Beta

- Runtime observation
- Paper trading stability
- Performance validation
- No new feature lanes planned
- Issue #1012 active hardening lane: live execution user_id guards (MAJOR, NARROW INTEGRATION)

## Non-Negotiable Rules

- ENABLE_LIVE_TRADING = false
- EXECUTION_PATH_VALIDATED = false
- CAPITAL_MODE_CONFIRMED = false
- RISK_CONTROLS_VALIDATED = false
- USE_REAL_CLOB = false
- Paper mode only until explicit owner decision
