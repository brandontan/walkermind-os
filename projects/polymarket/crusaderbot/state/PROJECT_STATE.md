Last Updated : 2026-05-05 00:10
Status       : R1-R11 merged to main. SENTINEL PASS. C1/C2/C3 resolved. Paper-default. Ready for R12a.

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

[IN PROGRESS]
- None — no open PRs

[NOT STARTED]
- R5 strategy config
- R6 signal engine (copy-trade + signal-following)
- R7 risk gate (13-step)
- R8 paper execution engine
- R9 exit logic (TP/SL + force-close)
- R10 auto-redeem (instant/hourly)
- R11 fee + referral accounting
- R12 ops + monitoring

[NEXT PRIORITY]
- R12a — CI/CD Pipeline (GitHub Actions)

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-merge cleanup)
