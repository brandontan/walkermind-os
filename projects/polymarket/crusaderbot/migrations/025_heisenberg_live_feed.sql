-- Migration 025: Seed CrusaderBot Live Feed for Heisenberg real-signal pipeline
-- Idempotent: INSERT ON CONFLICT DO NOTHING
-- Apply after 024_signal_scan_engine_seed.sql

BEGIN;

-- Create the live feed row. operator_id defaults to the oldest user (same pattern as 024).
-- The fixed UUID must match LIVE_FEED_ID in jobs/market_signal_scanner.py.
INSERT INTO signal_feeds (id, name, slug, operator_id, status, description,
                          subscriber_count, is_demo, created_at, updated_at)
SELECT
    '00000000-0000-0000-0002-000000000001'::uuid,
    'CrusaderBot Live Feed',
    'crusaderbot-live',
    id,
    'active',
    'Real-time signal feed powered by Heisenberg market data. Non-demo signals only.',
    0,
    FALSE,
    NOW(),
    NOW()
FROM users
ORDER BY created_at ASC
LIMIT 1
ON CONFLICT DO NOTHING;

COMMIT;
