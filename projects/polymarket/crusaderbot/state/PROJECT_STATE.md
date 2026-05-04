Last Updated : 2026-05-04 15:03
Status       : R4 deposit watcher + ledger lane MERGED (PR #850). Paper mode. All activation guards OFF. R5 strategy config is next. WARP🔹CMD to determine post-R4 validation path (MAJOR tier — WARP•SENTINEL sweep may be required before R5 opens).

[COMPLETED]
- PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT)
- crusaderbot/ project path established under projects/polymarket/
- R1 skeleton — FastAPI + DB + Redis + Telegram polling + migrations + risk constants (PR #847 merged)
- R2 onboarding + HD wallet generation (PR #848 merged)
- R3 operator allowlist + Tier 2 gate (PR merged)
- R4 deposit watcher + ledger crediting (PR #850 merged)

[IN PROGRESS]
- None

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
- WARP🔹CMD: determine post-R4 validation path. R4 was MAJOR tier — WARP•SENTINEL sweep may be required before R5 opens.
- R5 strategy config (risk profile + filters + capital alloc) — open when WARP🔹CMD confirms gate clear.

[KNOWN ISSUES]
- None
