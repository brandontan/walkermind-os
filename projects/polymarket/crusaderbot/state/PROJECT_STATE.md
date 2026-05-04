Last Updated : 2026-05-04 08:36
Status       : R2 onboarding + HD wallet generation lane open. Paper mode. All activation guards OFF. /start now provisions per-user HD wallet on first contact; subsequent /start calls return existing address (idempotent). Private keys encrypted at rest via Fernet, never logged or surfaced.

[COMPLETED]
- PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT)
- crusaderbot/ project path established under projects/polymarket/
- R1 skeleton — FastAPI + DB + Redis + Telegram polling + migrations + risk constants (PR #847 merged)

[IN PROGRESS]
- crusaderbot-r2-onboarding (PR open against main, awaiting WARP🔹CMD review)

[NOT STARTED]
- R3 operator allowlist
- R4 deposit watcher + ledger
- R5 strategy config
- R6 signal engine (copy-trade + signal-following)
- R7 risk gate (13-step)
- R8 paper execution engine
- R9 exit logic (TP/SL + force-close)
- R10 auto-redeem (instant/hourly)
- R11 fee + referral accounting
- R12 ops + monitoring

[NEXT PRIORITY]
- R3 — operator allowlist (Tier 2 access gate)

[KNOWN ISSUES]
- None
