-- 091_live_trade_activation.sql — WARP-92 global live-trade activation flag.
--
-- Seeds the Condition-2 GLOBAL admin toggle into system_settings (the same
-- key/value bag the kill switch uses; see 007_ops.sql). This is the only
-- net-new state for the global activation layer.
--
--   global_live_trading_enabled  'true'|'false' — operator-flipped master
--                                switch. Read on the hot path by
--                                domain/ops/global_live_gate.py (cached 30s)
--                                and composed into the execution router as a
--                                hard AND with the env guard and per-user
--                                opt-in. Seeded to 'false' so live trading is
--                                NEVER enabled by default — fail-safe to paper.
--
-- No schema change. Idempotent: ON CONFLICT DO NOTHING preserves any value an
-- operator may have already set on a re-run / rolling deploy.

INSERT INTO system_settings (key, value)
VALUES ('global_live_trading_enabled', 'false')
ON CONFLICT (key) DO NOTHING;
