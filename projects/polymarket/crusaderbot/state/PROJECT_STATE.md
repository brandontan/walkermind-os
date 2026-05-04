Last Updated : 2026-05-04 19:30
Status       : R4 deposit watcher + ledger lane open. Paper mode. All activation guards OFF. Alchemy WS subscription to USDC Transfer events on Polygon, in-process address-map filter, atomic deposit-insert + ledger-credit transaction keyed on UNIQUE (tx_hash, log_index), reorg-removed logs gated, Tier 3 auto-bump on balance >= MIN_DEPOSIT_USDC, Telegram deposit-confirmed notification. /wallet (all tiers) and /deposit (Tier 2+) registered. Codex auto-review P1 findings addressed in follow-up commit.

[COMPLETED]
- PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT)
- crusaderbot/ project path established under projects/polymarket/
- R1 skeleton — FastAPI + DB + Redis + Telegram polling + migrations + risk constants (PR #847 merged)
- R2 onboarding + HD wallet generation (PR #848 merged)
- R3 operator allowlist + Tier 2 gate (PR merged)

[IN PROGRESS]
- crusaderbot-r4-deposit-watcher (PR open against main, awaiting WARP🔹CMD review + WARP•SENTINEL validation)

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
- WARP•SENTINEL validation required for R4 deposit watcher before merge.
  Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-r4-deposit-watcher.md
  Tier: MAJOR

[KNOWN ISSUES]
- None
