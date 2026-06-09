-- migration 075 — register weather strategy in the operator strategies table
--
-- Lane: WARP/ROOT/weather-strategy-pipeline (MAJOR — execution pipeline)
--
-- Adds the `weather` strategy row to the operator toggle table so the
-- admin console can enable/disable it globally. Default enabled=TRUE so it
-- goes live on the next deploy without a manual admin toggle.
--
-- FAIL-SAFE preserved: signal_scan_job._refresh_disabled_strategies() treats
-- a missing row as enabled=TRUE, but an explicit row avoids ambiguity in the
-- admin console and the /autotrade/preset-availability endpoint.

INSERT INTO strategies (name, enabled)
VALUES ('weather', TRUE)
ON CONFLICT (name) DO NOTHING;
