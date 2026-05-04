# CrusaderBot — Roadmap

**Project:** projects/polymarket/crusaderbot
**Blueprint:** docs/blueprint/crusaderbot.md (v3.1 LOCKED)
**Last Updated:** 2026-05-04 13:04 Asia/Jakarta

## Build Path (Replit → Claude Code MVP)

| Lane | Name | Status | Tier | Notes |
|---|---|---|---|---|
| R1 | Skeleton — FastAPI + DB + Redis + Telegram polling + migrations | ✅ Done | STANDARD | Merged via PR #847 |
| R2 | User onboarding + HD wallet generation | ✅ Done | STANDARD | Merged via PR #848 |
| R3 | Operator allowlist (Tier 2 access gate) | ✅ Done | STANDARD | Merged via PR #849 |
| R4 | Deposit watcher + ledger crediting | ❌ Not Started | MAJOR | — |
| R5 | Strategy config (risk profile + filters + capital alloc) | ❌ Not Started | STANDARD | — |
| R6 | Signal engine (copy-trade + signal-following) | ❌ Not Started | MAJOR | — |
| R7 | Risk gate (13-step pre-execution) | ❌ Not Started | MAJOR | — |
| R8 | Paper execution engine | ❌ Not Started | MAJOR | — |
| R9 | Exit logic (TP/SL + strategy exit + force-close) | ❌ Not Started | MAJOR | — |
| R10 | Auto-redeem (instant/hourly modes) | ❌ Not Started | STANDARD | — |
| R11 | Fee + referral accounting (default OFF) | ❌ Not Started | STANDARD | — |
| R12 | Ops + monitoring (operator dashboard + alerts) | ❌ Not Started | STANDARD | — |

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
