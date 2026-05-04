Last Updated : 2026-05-05 02:59
Status       : R1-R12a merged. CI/CD pipeline live (GitHub Actions + Fly.io). Paper-default. Next: configure FLY_API_TOKEN secret + proceed to R12b.

[COMPLETED]
- PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT)
- crusaderbot/ project path established under projects/polymarket/
- R1 skeleton — FastAPI + DB + Redis + Telegram polling + migrations + risk constants (PR #847 merged)
- R2 onboarding + HD wallet generation (PR #848 merged)
- R3 operator allowlist + Tier 2 gate (PR merged)
- PR #852 — feat(crusaderbot): import full Replit build R1-R11
- PR #853 — sentinel: crusaderbot-replit-import PASS (post-fix)
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12a — CI/CD Pipeline (GitHub Actions + Fly.io) merged — PR #855

[IN PROGRESS]
- None.

[NOT STARTED]
- R12b — Fly.io Health Alerts
- R12c — Auto-Close / Take-Profit (MAJOR — execution path)
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary
- R12 — Deployment (Fly.io) — final (MAJOR)

[NEXT PRIORITY]
- Configure FLY_API_TOKEN repo secret + fly secrets for runtime env (post-R12a merge action)
- Proceed to R12b — Fly.io Health Alerts

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
