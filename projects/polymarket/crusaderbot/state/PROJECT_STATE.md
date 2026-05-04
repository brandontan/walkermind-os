Last Updated : 2026-05-04 23:51
Status       : PR #852 (WARP/CRUSADERBOT-REPLIT-IMPORT) merged — full 42-file Replit build superseding R1–R11 stubs. PR #853 (WARP•SENTINEL audit) merged — BLOCKED verdict, 64/100, 3 critical findings (C1 Kelly absent; C2 migrations/004 non-idempotent; C3 scheduler tier-promote on any deposit). Awaiting WARP🔹CMD direction on C1/C2/C3 remediation before next lane opens. Paper mode. All activation guards OFF.

[COMPLETED]
- PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT)
- crusaderbot/ project path established under projects/polymarket/
- R1 skeleton — FastAPI + DB + Redis + Telegram polling + migrations + risk constants (PR #847 merged)
- R2 onboarding + HD wallet generation (PR #848 merged)
- R3 operator allowlist + Tier 2 gate (PR merged)
- WARP/CRUSADERBOT-REPLIT-IMPORT — full 42-file Replit build (R1–R11) imported, supersedes stubs (PR #852 merged)
- WARP•SENTINEL crusaderbot-replit-import — audit report filed, verdict BLOCKED 64/100 (PR #853 merged)

[IN PROGRESS]
- Remediation of C1/C2/C3 critical findings from SENTINEL BLOCKED verdict — awaiting WARP🔹CMD direction

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
- WARP🔹CMD decision on C1/C2/C3 remediation: WARP•FORGE fix lane for Kelly enforcement, migrations/004 idempotency, scheduler tier-promote gate. Source: projects/polymarket/crusaderbot/reports/sentinel/crusaderbot-replit-import.md. Tier: MAJOR.

[KNOWN ISSUES]
- C1 Kelly fraction not enforced; capital_alloc_pct accepts 100% (setup.py:237-239 + copy_trade.py:30 + constants.py:4 declared but never referenced).
- C2 migrations/004_deposit_log_index.sql:14-16 uses bare ADD CONSTRAINT (no IF NOT EXISTS support in Postgres) — bot fails restart after first deploy.
- C3 scheduler.py:154-158 promotes Tier 3 on any deposit credit, ignoring MIN_DEPOSIT_USDC=50.
