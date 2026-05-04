Last Updated : 2026-05-04 21:52
Status       : WARP•SENTINEL audit of CrusaderBot R1–R11 Replit import (PR #852, audited commit 8c6aded3) completed — verdict BLOCKED, 64/100, 3 critical findings (C1 Kelly absent + capital_alloc_pct accepts 100%; C2 migrations/004 non-idempotent → restart fails; C3 scheduler.watch_deposits promotes Tier 3 on any deposit). P1 fixes verified correct (deposit dedup on (tx_hash,log_index), live close idempotency, polygon log_index passthrough). Audit report on PR #853. Paper mode. All activation guards OFF.

[COMPLETED]
- PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT)
- crusaderbot/ project path established under projects/polymarket/
- R1 skeleton — FastAPI + DB + Redis + Telegram polling + migrations + risk constants (PR #847 merged)
- R2 onboarding + HD wallet generation (PR #848 merged)
- R3 operator allowlist + Tier 2 gate (PR merged)

[IN PROGRESS]
- WARP/CRUSADERBOT-REPLIT-IMPORT (PR #852, audited commit 8c6aded3) — Sentinel BLOCKED with 3 critical findings; awaiting WARP🔹CMD remediation decision
- WARP/sentinel-crusaderbot-replit-import (PR #853) — audit-report PR carrying projects/polymarket/crusaderbot/reports/sentinel/crusaderbot-replit-import.md

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
- WARP🔹CMD decision on PR #852 remediation. Sentinel verdict BLOCKED until C1/C2/C3 patched, then re-validation.
  Source: projects/polymarket/crusaderbot/reports/sentinel/crusaderbot-replit-import.md
  Tier: MAJOR

[KNOWN ISSUES]
- C1 Kelly fraction not enforced; capital_alloc_pct accepts 100% (setup.py:237-239 + copy_trade.py:30 + constants.py:4 declared but never referenced).
- C2 migrations/004_deposit_log_index.sql:14-16 uses bare ADD CONSTRAINT (no IF NOT EXISTS support in Postgres) — bot fails restart after first deploy.
- C3 scheduler.py:154-158 promotes Tier 3 on any deposit credit, ignoring MIN_DEPOSIT_USDC=50.
