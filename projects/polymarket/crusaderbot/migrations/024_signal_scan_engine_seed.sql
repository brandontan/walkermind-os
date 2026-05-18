-- Migration 024: Signal Scan Engine — seed feeds, enroll users, wire pipeline
-- Idempotent: all inserts use ON CONFLICT DO NOTHING or WHERE NOT EXISTS
-- Apply after 023_user_tiers.sql

BEGIN;

-- 1. Seed demo signal feed (fixed UUID for idempotency)
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

-- 2. Seed demo market (enables end-to-end test without waiting for market_sync)
INSERT INTO markets (id, slug, question, category, status,
                     yes_price, no_price, liquidity_usdc,
                     resolved, synced_at)
VALUES (
    'demo-market-will-btc-100k-2026',
    'will-btc-reach-100k-2026',
    'Will Bitcoin reach $100,000 by end of 2026?',
    'Crypto',
    'active',
    0.10,
    0.90,
    50000.0,
    FALSE,
    NOW()
)
ON CONFLICT (id) DO NOTHING;

-- 3. Seed demo signal publication pointing at the demo market (YES edge)
-- Guard: only insert if the demo feed was successfully created above
-- (on a fresh DB with no users, the feed insert above produces 0 rows,
--  so this WHERE EXISTS prevents a FK violation that would abort startup migrations)
INSERT INTO signal_publications (feed_id, market_id, side, target_price,
                                  signal_type, payload, exit_signal,
                                  published_at, expires_at, is_demo)
SELECT
    '00000000-0000-0000-0001-000000000001'::uuid,
    'demo-market-will-btc-100k-2026',
    'YES',
    0.10,
    'edge_finder',
    '{"strategy":"edge_finder","liquidity":50000,"question":"Will Bitcoin reach $100,000 by end of 2026?","confidence":0.65,"size_usdc":10.0,"yes_price":0.10,"signal_reason":"yes_edge"}'::jsonb,
    FALSE,
    NOW(),
    NOW() + INTERVAL '4 hours',
    TRUE
WHERE EXISTS (
    SELECT 1 FROM signal_feeds
     WHERE id = '00000000-0000-0000-0001-000000000001'::uuid AND status = 'active'
)
AND NOT EXISTS (
    SELECT 1 FROM signal_publications
     WHERE feed_id = '00000000-0000-0000-0001-000000000001'::uuid
       AND market_id = 'demo-market-will-btc-100k-2026'
       AND side = 'YES'
       AND exit_signal = FALSE
       AND exit_published_at IS NULL
);

-- 4. Promote all existing users to access_tier >= 3 (unblocks the scanner filter)
UPDATE users SET access_tier = 3 WHERE access_tier < 3;

-- 5. Enroll all users in signal_following strategy (upsert, weight 10%)
INSERT INTO user_strategies (user_id, strategy_name, weight, enabled, created_at)
SELECT id, 'signal_following', 0.10, TRUE, NOW()
FROM users
ON CONFLICT DO NOTHING;

-- 6. Subscribe all users to the demo feed
INSERT INTO user_signal_subscriptions (user_id, feed_id, subscribed_at, is_demo)
SELECT u.id,
       '00000000-0000-0000-0001-000000000001'::uuid,
       NOW(),
       TRUE
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM user_signal_subscriptions s
     WHERE s.user_id = u.id
       AND s.feed_id = '00000000-0000-0000-0001-000000000001'::uuid
       AND s.unsubscribed_at IS NULL
);

COMMIT;
