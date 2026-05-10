Last Updated : 2026-05-10 14:45 Asia/Jakarta
Status       : Post-merge state sync complete. PR #923, #924, #925, #926, #927, and #928 are merged. Open PRs: 0. Current focus: Phase 5E Copy Trade dashboard + wallet discovery. Runtime posture: PAPER ONLY. Activation guards: NOT SET. No code/runtime/guard changes in this sync.

[COMPLETED]
- Phase 4A-4E CLOB integration merged through PR #911, #912, #913, #915, #919 with required SENTINEL approvals.
- Supabase asyncpg prepared-statement fix merged in PR #923; PR #922 closed unmerged as superseded.
- Phase 5A global handlers merged in PR #924.
- Phase 5C strategy presets merged in PR #925; SENTINEL APPROVED 92/100.
- Phase 5B dashboard hierarchy redesign merged in PR #926; SENTINEL APPROVED 97/100.
- Phase 5 post-merge tracker merged in PR #927.
- Phase 5D 2-column grid + Copy/Auto Trade menu split merged in PR #928; 57/57 Phase 5D + preset tests green.

[IN PROGRESS]
- None.

[NOT STARTED]
- Phase 5E Copy Trade dashboard + wallet discovery.
- Phase 5G parallel path.
- WARP/CRUSADERBOT-MAINNET-ONCHAIN-PREFLIGHT.
- WARP/CRUSADERBOT-OPS-CIRCUIT-RESET.
- R13 growth backlog: leaderboard, backtesting, multi-signal fusion, admin web dashboard, referral system, strategy marketplace.

[NEXT PRIORITY]
- Dispatch Phase 5E from clean post-merge state.
- Keep activation guards NOT SET. No live trading activation, no capital mode change, no real order path, no owner guard flip.

[KNOWN ISSUES]
- /deposit has no tier gate (intentional, non-blocking).
- check_alchemy_ws is TCP-only and does not perform full WebSocket handshake.
- ENABLE_LIVE_TRADING code default in config.py is True (legacy); fly.toml [env] overrides to false. Alignment deferred to WARP/config-guard-default-alignment.
- integrations/polymarket.py _build_clob_client() is dead in the live execution path after Phase 4B but still indirectly referenced by submit_live_redemption(); cleanup deferred.
- Activation guards remain NOT SET and must not be changed without owner decision.
