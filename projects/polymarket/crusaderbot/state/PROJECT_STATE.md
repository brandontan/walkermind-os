Last Updated : 2026-05-04 13:04
Status       : R3 allowlist gate lane MERGED (PR #849). Paper mode. All activation guards OFF. Tier 2 allowlist (in-memory, asyncio.Lock-guarded) + /allowlist operator command (add/remove/list) live; require_tier decorator scaffolded for future Tier 2+ commands. Next: R4 deposit watcher + ledger.

[COMPLETED]
- PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT)
- crusaderbot/ project path established under projects/polymarket/
- R1 skeleton — FastAPI + DB + Redis + Telegram polling + migrations + risk constants (PR #847 merged)
- R2 onboarding + HD wallet generation (PR #848 merged)
- R3 operator allowlist + Tier 2 access gate (PR #849 merged)

[IN PROGRESS]
- None

[NOT STARTED]
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
- R4 — deposit watcher + ledger crediting

[KNOWN ISSUES]
- None
