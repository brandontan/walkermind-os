# CrusaderBot — Roadmap

**Project:** projects/polymarket/crusaderbot
**Blueprint:** docs/blueprint/crusaderbot.md (v3.1 LOCKED)
**Last Updated:** 2026-05-05 00:10 Asia/Jakarta

## Build Path (Replit → Claude Code MVP)

| Lane | Name | Status | Tier | Notes |
|---|---|---|---|---|
| R1 | Skeleton — FastAPI + DB + Redis + Telegram polling + migrations | ✅ Done | STANDARD | Merged via PR #852, SENTINEL PASS |
| R2 | User onboarding + HD wallet generation | ✅ Done | STANDARD | Merged via PR #852, SENTINEL PASS |
| R3 | Operator allowlist (Tier 2 access gate) | ✅ Done | STANDARD | Merged via PR #852, SENTINEL PASS |
| R4 | Deposit watcher + ledger crediting | ✅ Done | MAJOR | Merged via PR #852, SENTINEL PASS |
| R5 | Strategy config (risk profile + filters + capital alloc) | ✅ Done | STANDARD | Merged via PR #852, SENTINEL PASS |
| R6 | Signal engine (copy-trade + signal-following) | ✅ Done | MAJOR | Merged via PR #852, SENTINEL PASS |
| R7 | Risk gate (13-step pre-execution) | ✅ Done | MAJOR | Merged via PR #852, SENTINEL PASS |
| R8 | Paper execution engine | ✅ Done | MAJOR | Merged via PR #852, SENTINEL PASS |
| R9 | Exit logic (TP/SL + strategy exit + force-close) | ✅ Done | MAJOR | Merged via PR #852, SENTINEL PASS |
| R10 | Auto-redeem (instant/hourly modes) | ✅ Done | STANDARD | Merged via PR #852, SENTINEL PASS |
| R11 | Fee + referral accounting (default OFF) | ✅ Done | STANDARD | Merged via PR #852, SENTINEL PASS |
| R12a | CI/CD Pipeline (GitHub Actions) | ❌ Not Started | STANDARD | Next priority |
| R12b | Fly.io Health Alerts | ❌ Not Started | STANDARD | — |
| R12c | Auto-Close / Take-Profit | ❌ Not Started | MAJOR | Order-path / execution — SENTINEL required |
| R12d | Live Opt-In Checklist | ❌ Not Started | MAJOR | Hard gate before EXE |
| R12e | Live → Paper Auto-Fallback | ❌ Not Started | MAJOR | — |
| R12f | Daily P&L Summary | ❌ Not Started | STANDARD | — |
| R12 | Deployment (Fly.io) — final | ❌ Not Started | MAJOR | After R12a-R12f |

## R12 — Detailed Lane Plan

### R12a — CI/CD Pipeline
GitHub Actions: pytest + docker build + flyctl deploy. Triggers on push to main.

### R12b — Fly.io Health Alerts
Cron ping `/health` every 1 min. Telegram alert to `OPERATOR_CHAT_ID` if down. Escalate if no recovery in 5 min.

### R12c — Auto-Close / Take-Profit
Scheduler polls open positions. Auto-submit close order at target price. Optional trailing stop (close if price drops X% from peak).

### R12d — Live Opt-In Checklist
Interactive Telegram flow before `EXECUTION_PATH_VALIDATED`. Steps: risk confirm → wallet balance verify → daily loss limit set → operator approval. Hard gate — cannot skip.

### R12e — Live to Paper Auto-Fallback
Monitor: RPC error rate, consecutive failed submissions, drawdown above threshold. Auto-switch to paper mode + notify operator. Manual re-activation required (safety by design).

### R12f — Daily P&L Summary
Scheduler job at 23:55 Asia/Jakarta daily. Per-user: trades today, win rate, realized P&L, open positions. Operator: total volume, active users, system health.

## R13 — Growth Backlog (post-MVP)

| Lane | Name | Status | Tier | Notes |
|---|---|---|---|---|
| R13a | Leaderboard | ❌ Backlog | STANDARD | — |
| R13b | Backtesting Engine | ❌ Backlog | STANDARD | — |
| R13c | Multi-Signal Fusion | ❌ Backlog | MAJOR | — |
| R13d | Web Dashboard (Admin) | ❌ Backlog | STANDARD | — |
| R13e | Referral System | ❌ Backlog | STANDARD | — |
| R13f | Strategy Marketplace | ❌ Backlog | STANDARD | — |

### R13a — Leaderboard
Paper P&L ranking, `/leaderboard` command, top 10. Updated daily via scheduler.

### R13b — Backtesting Engine
Replay historical Polymarket data. Output: win rate, Sharpe ratio, max drawdown, EV.

### R13c — Multi-Signal Fusion
Add sentiment + on-chain volume to copy-trade signal. Weighted combiner, configurable per tier.

### R13d — Web Dashboard (Admin)
React + FastAPI, uses existing `/api/admin/*` endpoints. Views: users, positions, P&L chart, scheduler status.

### R13e — Referral System
Unique referral code, fee discount for referee. `referrals` table: `referrer_id`, `referee_id`, `total_earned`.

### R13f — Strategy Marketplace
Tier 4 users publish named strategies. Subscription model, platform takes 10%.

## Activation Guards (default OFF)

| Guard | Owner | Status |
|---|---|---|
| `EXECUTION_PATH_VALIDATED` | Engineering | ⚪ OFF |
| `CAPITAL_MODE_CONFIRMED` | Operator | ⚪ OFF |
| `ENABLE_LIVE_TRADING` | Owner | ⚪ OFF |
| `RISK_CONTROLS_VALIDATED` | SENTINEL | ⚪ OFF |
| `SECURITY_HARDENING_VALIDATED` | SENTINEL | ⚪ OFF |
| `FEE_COLLECTION_ENABLED` | Owner | ⚪ OFF |
| `AUTO_REDEEM_ENABLED` | Engineering | ⚪ OFF |

## Boundary

- Paper mode only until live activation guards are SET
- Risk constants hard-wired in `crusaderbot/domain/risk/constants.py` — PR-protected, never overridable at runtime
- Multi-user isolation enforced from R2 onward (per-user wallet, per-user sub-account ledger)
- Live trading requires owner gate + operator approval + SENTINEL APPROVED on R7/R8/R9 lanes

## Phase numbering note

Blueprint v3.1 §13 defines product-gate phases (Phase 0 owner gates → Phase 11 open beta). The R1–R12 lane sequence above is the **implementation lane** numbering for the Replit→Claude Code MVP build path; lanes group code work, blueprint phases group product-gate decisions. The two are aligned:

- Blueprint Phase 0 → owner-gate decisions (out of code lane scope)
- Blueprint Phase 1 → R1 (this lane) + R2 wallet foundation
- Blueprint Phase 2-3 → R2-R6
- Blueprint Phase 4 → R7-R8 (real CLOB execution requires guard activation)
- Blueprint Phase 5 → R3 + R5 (Telegram UX surfaces)
- Blueprint Phase 6 → R11
- Blueprint Phase 7 → R10
- Blueprint Phase 8 → multi-user live audit (post-R8)
- Blueprint Phase 9 → R12
- Blueprint Phase 10-11 → closed/open beta (post-R12)

Reference: `docs/blueprint/crusaderbot.md` §6 (Risk System), §12 (Activation Guards), §13 (Roadmap).
