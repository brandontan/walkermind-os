-- Migration 031: Signal Scanner — backfill feed seeds + user enrollment
-- Fixes: demo/live feeds missing if 024/025 ran on empty DB;
--        users created after 024 not enrolled or subscribed;
--        access_tier < 3 blocking paper-mode signal scan.
-- Idempotent: all writes use ON CONFLICT DO NOTHING or WHERE NOT EXISTS.
-- Apply after 030_job_runs_metadata.sql

BEGIN;

-- 1. Re-seed demo feed (guard: needs at least one user as operator)
INSERT INTO signal_feeds (id, name, slug, operator_id, status, description,
                          subscriber_count, is_demo, created_at, updated_at)
SELECT
    '00000000-0000-0000-0001-000000000001'::uuid,
    'CrusaderBot Demo Feed',
    'crusaderbot-demo',
    id,
    'active',
    'Auto-generated demo feed for paper trading. Signals from edge_finder strategy.',
    0,
    TRUE,
    NOW(),
    NOW()
FROM users
ORDER BY created_at ASC
LIMIT 1
ON CONFLICT DO NOTHING;

-- 2. Re-seed live feed (same guard)
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

-- 3. Enroll all users in signal_following strategy (upsert — idempotent)
INSERT INTO user_strategies (user_id, strategy_name, weight, enabled, created_at)
SELECT id, 'signal_following', 0.10, TRUE, NOW()
FROM users
ON CONFLICT DO NOTHING;

-- 4. Subscribe all users to demo feed (only if feed was seeded successfully)
INSERT INTO user_signal_subscriptions (user_id, feed_id, subscribed_at, is_demo)
SELECT u.id,
       '00000000-0000-0000-0001-000000000001'::uuid,
       NOW(),
       TRUE
FROM users u
WHERE EXISTS (
    SELECT 1 FROM signal_feeds
     WHERE id = '00000000-0000-0000-0001-000000000001'::uuid AND status = 'active'
)
AND NOT EXISTS (
    SELECT 1 FROM user_signal_subscriptions s
     WHERE s.user_id = u.id
       AND s.feed_id = '00000000-0000-0000-0001-000000000001'::uuid
       AND s.unsubscribed_at IS NULL
);

-- 5. Align access_tier with role model — paper is open to all users
UPDATE users SET access_tier = 3 WHERE access_tier < 3;

COMMIT;
