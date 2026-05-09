Last Updated : 2026-05-10 02:59 Asia/Jakarta
Status       : Phase 4E CLOB Resilience is merged on main via PR #919 (merge commit f18e25cb5cb516f6d41e0e87fff1c0915d489f45) after WARP•SENTINEL APPROVED 94/100 with zero critical issues. Sentinel report is committed at projects/polymarket/crusaderbot/reports/sentinel/resilience.md. Phase 4 CLOB integration is now 5/5 merged: adapter/auth, execution rewire, order lifecycle, websocket fills, and resilience/mainnet local preflight. Current runtime posture remains PAPER ONLY: USE_REAL_CLOB default False, ENABLE_LIVE_TRADING not enabled, EXECUTION_PATH_VALIDATED not set, CAPITAL_MODE_CONFIRMED not set, and no owner activation guard was flipped. Live readiness is improved but live trading is still blocked until owner/operator activation guards are set and preflight passes. No open PRs. No open GitHub issues.

[COMPLETED]
- Phase 4A CLOB Adapter -- PR #911 merged, MAJOR, SENTINEL APPROVED 89/100, branch WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER.
- Phase 4B Execution Rewire -- PR #912 merged, MAJOR, SENTINEL APPROVED 92/100, branch WARP/CRUSADERBOT-PHASE4B-EXECUTION-REWIRE.
- Phase 4C Order Lifecycle -- PR #913 merged, MAJOR, SENTINEL APPROVED 96/100, branch WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE.
- Phase 4D WebSocket Order Fills -- PR #915 merged, MAJOR, SENTINEL APPROVED 98/100, branch WARP/CRUSADERBOT-PHASE4D-WEBSOCKET-FILLS.
- Phase 4E CLOB Resilience -- PR #919 merged, MAJOR, FULL RUNTIME INTEGRATION, SENTINEL APPROVED 94/100, branch WARP/CRUSADERBOT-PHASE4E-RESILIENCE.
- Sentinel gate trail for Phase 4E -- Issue #920 closed completed after PR #921 merged Sentinel report/state into the Phase 4E source branch and PR #919 merged to main.
- R12 final Fly.io production paper deploy -- Issue #900 is closed completed in GitHub; old pending wording is superseded by current live issue state.
- Phase 3 strategy plane -- P3a/P3b/P3c/P3d merged with required Sentinel coverage; strategy registry, copy trade, signal following, and per-user signal scan queue are live in paper-safe posture.
- Demo data seeding -- PR #908 merged, STANDARD, SENTINEL APPROVED 98/100; migration 014, seed/cleanup scripts, runbook, and tests landed.
- Operator dashboard and kill switch baseline -- PR #874 merged, STANDARD; /ops dashboard and operator controls are available.

[IN PROGRESS]
- None -- PR #919 is merged, PR #921 is merged, Issue #920 is closed, and no open GitHub issues or PRs remain.

[NOT STARTED]
- WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT -- on-chain wallet, allowance, balance, and signer readiness checks complementing scripts/mainnet_preflight.py; no live trading activation and no real orders.
- WARP/CRUSADERBOT-OPS-CIRCUIT-RESET -- operator endpoint / Telegram command to force_close the CLOB circuit breaker after incident review; no broker calls and no guard flips.
- R13a Leaderboard -- paper P&L ranking, /leaderboard command, top 10, daily scheduler update.
- R13b Backtesting Engine -- replay historical Polymarket data and output win rate, Sharpe ratio, max drawdown, and EV.
- R13c Multi-Signal Fusion -- combine sentiment and on-chain volume into copy-trade signal weighting; MAJOR if strategy execution behavior changes.
- R13d Web Dashboard (Admin) -- React + FastAPI admin views for users, positions, P&L chart, and scheduler status.
- R13e Referral System -- referral code, referee discount, and referral accounting.
- R13f Strategy Marketplace -- tier 4 named strategies, subscription model, and 10% platform take.

[NEXT PRIORITY]
- Dispatch WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT as the next safety lane before any owner live-trading decision. Recommended tier: MAJOR. Claim: FULL RUNTIME INTEGRATION if it touches real wallet/on-chain readiness; SENTINEL REQUIRED. Scope: read-only wallet/chain/preflight verification only, no order submission, no ENABLE_LIVE_TRADING, no USE_REAL_CLOB default flip.
- Keep activation guards NOT SET. No live trading activation, no capital mode change, no real order, no owner guard flip.
- R13a Leaderboard is queued after the safety lane if product/growth work is prioritized over mainnet readiness.

[KNOWN ISSUES]
- /deposit has no tier gate (intentional, non-blocking).
- check_alchemy_ws is TCP-only and does not perform a full WebSocket handshake; follow-up low priority.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to "false" so production posture is correct. Code default alignment remains deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP.
- Activation guards remain NOT SET and must not be changed without owner decision.
- R13 backlog is post-MVP growth work; none is required to keep current paper-safe runtime functional.
- [DEFERRED] Concurrent HALF_OPEN trial race in CircuitBreaker._record_failure may multiply on_open invocations and restart cool-down; P2, no safety implication.
- [DEFERRED] CLOB circuit-open Telegram alert text uses plain markdown rather than MarkdownV2; P2, acceptable for static template.
- [DEFERRED] Ops dashboard CLOB circuit card refreshes only via page-level 30s meta refresh; SSE/WS push is future enhancement.
- [DEFERRED] Package-level single-instance CircuitBreaker is adequate for single-broker steady state; per-broker instances can be passed via circuit_breaker kwarg if needed.

<!-- CD verify: 2026-05-10 02:59 -->
