-- migration 076 — persist opaque per-strategy metadata on positions
--
-- Lane: WARP/weather-strategy-metadata (MAJOR — execution chain)
--
-- Adds positions.strategy_metadata JSONB so a strategy's signal-time snapshot
-- (weather: city, bucket bounds, entry forecast mean, high-water price) rides
-- with the position and is replayed into the strategy exit hook by
-- exit_watcher.registry_strategy_evaluator. Without this column the weather
-- trailing-stop (Exit 2) and adaptive forecast-shift (Exit 4) fall back to
-- their graceful no-op paths because the payload lacks bucket/city data.
--
-- Additive + idempotent: NULL default keeps every existing row + every
-- non-weather INSERT unchanged. asyncpg has no pool-level JSONB codec, so the
-- writer json.dumps() the dict with a $N::jsonb cast and the reader json.loads()
-- the returned text (matches the system_alerts.metadata convention, mig 072).

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS strategy_metadata JSONB DEFAULT NULL;
