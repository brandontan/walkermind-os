Last Updated : 2026-05-10 21:30
Status       : Fast Track roadmap selected by Mr. Walker. CrusaderBot is live on Fly.io in PAPER ONLY mode after Phase 5 UX redesign and asyncpg Supabase pooler hotfix. Post-merge sync lane is closed; no open PRs. Current active lane is Fast Track Week 1 preparation: Track A trade engine + TP/SL is next, but activation guards remain NOT SET and no live trading is enabled.

[COMPLETED]
- Phase 1 project restructure complete.
- Phase 2 wallet + deposit foundation complete.
- Phase 3 strategy registry + signals complete.
- Phase 4 real CLOB integration complete through Phase 4A-4E; live path remains guarded, USE_REAL_CLOB default False, and production is paper-safe.
- Phase 4 hotfix asyncpg + Supabase Supavisor complete via PR #923; statement_cache_size=0 prevents prepared-statement cache failures on transaction pooler.
- Phase 5 Telegram Auto-Trade UX complete through 5A-5J: global handlers, dashboard hierarchy, presets, 2-column menu, Copy Trade dashboard/wizard/edit, customize wizard, onboarding, My Trades, Emergency lock, qrcode dependency hotfix.
- State sync after PRs #923-#939 complete; PROJECT_STATE / ROADMAP / WORKTODO aligned to merged Phase 5 truth.
- Fast Track roadmap selected by Mr. Walker on 2026-05-10; Standard roadmap rejected for current execution posture.

[IN PROGRESS]
- Observation / runtime monitoring remains active in paper mode while Fast Track work begins.
- Fast Track Week 1 is the active delivery path: Track A first, then Track B and Track C after Track A merge posture is valid.
- Current production posture: Telegram @CrusaderBot live, Fly.io app running, Supabase project ykyagjdeqcgcktnpdhes, test user walk3r69 has $1000 paper USDC and Full Auto aggressive preset.
- Activation guards remain OFF: ENABLE_LIVE_TRADING=false, EXECUTION_PATH_VALIDATED=false, CAPITAL_MODE_CONFIRMED=false, RISK_CONTROLS_VALIDATED=false.

[NOT STARTED]
- Fast Track Track A -- Trade engine + TP/SL: signal fires -> risk gate -> order created -> paper position opened; TP/SL background worker auto-closes positions. MAJOR; SENTINEL required.
- Fast Track Track B -- Copy Trade execution: active copy_trade_tasks monitor target wallets and mirror paper positions with spend/min-size caps. MAJOR; SENTINEL required; depends on Track A.
- Fast Track Track C -- Trade notifications: entry, exit, and copy trade Telegram notifications. STANDARD; merge after Track A integration surface is available.
- Fast Track Track D -- Risk caps + kill switch hardening: hard exposure caps, daily loss guard, max open positions, Telegram/DB/env kill paths. MAJOR; SENTINEL required.
- Fast Track Track E -- Daily P&L report: scheduled Telegram daily summary. STANDARD.
- Fast Track Week 2 -- Live gate + UI premium pack + charts/insights + referral/share/fee prep.
- Fast Track Week 3 -- Multi-user isolation audit + access tiers + admin + onboarding polish.
- Fast Track Week 4 -- Closed beta observation; no new feature PRs planned in that week.

[NEXT PRIORITY]
- Create WARP•FORGE issue for Fast Track Track A.
- Dispatch WARP•FORGE Track A on branch WARP/crusaderbot-fast-trade-engine.
- Require report at projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-trade-engine.md and state updates in the same PR.
- After Track A PR is ready and pre-handoff checks pass, create separate WARP•SENTINEL issue for Track A validation before merge.
- Do not flip live activation guards during Track A.

[KNOWN ISSUES]
- /deposit has no tier gate; intentional and non-blocking.
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; low-priority follow-up.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to false so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without explicit owner decision.
- R13 backlog is post-MVP growth work and not required for current paper-safe runtime.
- [DEFERRED] Concurrent HALF_OPEN trial race in CircuitBreaker._record_failure may multiply on_open invocations and restart cool-down; P2, no safety implication.
- [DEFERRED] CLOB circuit-open Telegram alert text uses plain markdown rather than MarkdownV2; P2, acceptable for static template.
- [DEFERRED] Ops dashboard CLOB circuit card refreshes only via page-level 30s meta refresh; SSE/WS push is future enhancement.
- [DEFERRED] Package-level single-instance CircuitBreaker is adequate for single-broker steady state; per-broker instances can be passed via circuit_breaker kwarg if needed.
