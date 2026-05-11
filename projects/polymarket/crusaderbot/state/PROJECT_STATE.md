Last Updated : 2026-05-11 23:15
Status       : Fast Track Week 1 Tracks A-E MERGED. Week 2 first lane -- CrusaderBot Premium PNL Insights UX (issue #963) MERGED via PR #965 at 6606c592222dea971b93d90318872dd273e83f91. /insights command, insights:refresh callback, dashboard:insights sub-handler, insights_kb, dashboard + my_trades nav updates, mode='paper' query boundary, _safe_md title escaping, signed PNL formatting, and 22 hermetic tests are complete. PR #964 was superseded and closed unmerged. Production remains LIVE on Telegram + Fly.io in PAPER ONLY posture. Activation guards remain OFF / NOT SET.

[COMPLETED]
- Phase 2 wallet + deposit foundation complete.
- Phase 3 strategy registry + signals complete.
- Phase 4 real CLOB integration complete through Phase 4A-4E; live path remains guarded, USE_REAL_CLOB default False, and production is paper-safe.
- Phase 5 Telegram Auto-Trade UX complete through 5A-5J.
- Fast Track roadmap selected by Mr. Walker on 2026-05-10; Standard roadmap rejected for current execution posture.
- Fast Track Track A -- Trade Engine + TP/SL worker MERGED PR #942 (2026-05-11). TradeEngine service layer; signal_scan_job routes through TradeEngine on all normal paths; 47 hermetic tests green.
- Fast Track Track B -- Copy Trade Execution MERGED PR #948 (2026-05-11). CopyTradeMonitor.run_once(), 020_copy_trade_execution.sql migration, 25 hermetic tests green.
- Fast Track Track C -- Trade notifications MERGED PR #951 (2026-05-11). TradeNotifier service layer; ENTRY/TP_HIT/SL_HIT/MANUAL/EMERGENCY/COPY_TRADE scaffold; 16 hermetic tests green.
- Fast Track Track D -- Live Gate Hardening MERGED PR #954 (2026-05-11). WARP-SENTINEL PPPROVED 92/100; 35 tests green.
- Fast Track Track E -- Daily P&L Report MERGED PR #962 (2026-05-11). Paper-mode daily Telegram P&L summary; opened/closed/W/L counts; no-trade empty state; scheduler callback wiring; 26 daily_pnl_summary tests green; issue #960 closed.
- Fast Track Week 2 first lane -- Premium PNL Insights UX MERGED PR #965 (2026-05-11, merge commit 6606c592222dea971b93d90318872dd273e83f91). /insights command, insights:refresh, dashboard:insights, insights_kb, dashboard + my_trades nav updates, paper-mode query boundary, _safe_md title escaping, signed PNL formatting, 22 hermetic tests green; issue #963 closed. PR #964 superseded and closed unmerged.

[IN PROGRESS]
- Observation / runtime monitoring remains active in paper mode.
- Current production posture: Telegram @CrusaderBot live, Fly.io app running, Supabase project ykyagjdeqcjcktnpdhes, test user walk3r69 has $1000 paper USDC and Full Auto aggressive preset.
- Activation guards remain OFF / NOT SET: ENABLE_LIVE_TRADING=false, EXECUTION_PATH_VALIDATED=false, CAPITAL_MODE_CONFIRMED=false, RISK_CONTROLS_VALIDATED=false. USE_REAL_CLOB remains false / not enabled.

[NOT STARTED]
- Fast Track Week 2 -- Live Gate Preparation (SENTINEL + owner checklist) -- NEXT LANE. Must remain PAPER ONLY until explicit owner activation decision. No activation guard flips.
- Fast Track Week 2 -- charts/insights follow-on and referral/share/fee prep.
- Fast Track Week 3 -- Multi-user isolation audit + access tiers + admin + onboarding polish.
- Fast Track Week 4 -- Closed beta observation; no new feature PRs planned in that week.

[NEXT PRIORITY]
- Execute Week 2 Live Gate Preparation as MAJOR: WARP-SENTINEL + owner checklist required before any live activation consideration.
- Do not flip activation guards.
- Keep production PAPER ONLY until explicit owner live activation decision.

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
- [DEFERRED] Forge report Known Issues section for Track D references stale parity patch approach (gate.get_settings); code is correct post-Codex fix; documentation drift only.
- [DEFERRED] check_price_deviation() not yet wired into live execution path; callable and tested; deferred until ENABLE_LIVE_TRADING gate is considered.
