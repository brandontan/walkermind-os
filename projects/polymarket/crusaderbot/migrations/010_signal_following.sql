-- 010_signal_following.sql
-- Phase 3c signal-following strategy persistence layer.
--
-- Adds three tables that back the operator-curated feed model behind
-- SignalFollowingStrategy:
--
--   signal_feeds              - one row per operator-managed feed. The slug
--                               is the stable user-facing identifier (e.g.
--                               "alpha-feed"); the UUID id is the FK target
--                               for publications + subscriptions. status
--                               gates whether new publications + new
--                               subscriptions are accepted.
--
--   signal_publications       - append-mostly log of signals an operator has
--                               published to a feed. Each row is either an
--                               entry signal (exit_signal = FALSE) or an
--                               exit announcement (exit_signal = TRUE).
--                               An entry row may also be retired via
--                               exit_published_at (set when the operator
--                               closes the original signal in place rather
--                               than publishing a new exit row). Strategy
--                               scan() reads exit_signal=FALSE only;
--                               evaluate_exit() reads either trigger.
--
--   user_signal_subscriptions - per-user feed enrolment. unsubscribed_at IS
--                               NULL means "currently subscribed". The
--                               application caps a user at 5 active
--                               subscriptions at the Telegram handler layer
--                               so the user gets an actionable error rather
--                               than a Postgres constraint exception. The
--                               partial UNIQUE on (user_id, feed_id) WHERE
--                               unsubscribed_at IS NULL is the dedup
--                               boundary so a user cannot hold two active
--                               subscriptions to the same feed.
--
-- Idempotency: every CREATE statement uses IF NOT EXISTS. The migration is
-- safe to re-run on every startup (matches the 008_strategy_tables.sql and
-- 009_copy_trade.sql patterns).
--
-- Path note: this file lives at projects/polymarket/crusaderbot/migrations/
-- per the issue spec. The runner database.run_migrations() reads from this
-- directory and applies it at startup.

-- ---------------------------------------------------------------------------
-- signal_feeds: operator-managed signal feed catalogue.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_feeds (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(100) NOT NULL,
    slug                VARCHAR(60) NOT NULL UNIQUE,
    operator_id         UUID NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'active',
    description         TEXT,
    subscriber_count    INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- signal_publications: append-mostly log of signals operators publish.
--
-- Read patterns:
--   * scan()           : feed_id IN (active subscriptions)
--                        AND exit_signal = FALSE
--                        AND (expires_at IS NULL OR expires_at > NOW())
--                        AND published_at > subscribed_at
--                      -> needs (feed_id, published_at) ordering.
--   * evaluate_exit()  : (feed_id, market_id) lookup with exit triggers.
--                      -> covered by feed_id prefix; no extra index.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_publications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feed_id             UUID NOT NULL REFERENCES signal_feeds(id) ON DELETE CASCADE,
    market_id           VARCHAR(100) NOT NULL,
    side                VARCHAR(8) NOT NULL,
    target_price        DOUBLE PRECISION,
    signal_type         VARCHAR(40) NOT NULL DEFAULT 'entry',
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    exit_signal         BOOLEAN NOT NULL DEFAULT FALSE,
    published_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    exit_published_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_signal_publications_feed_published
    ON signal_publications (feed_id, published_at DESC);

-- ---------------------------------------------------------------------------
-- user_signal_subscriptions: per-user feed enrolment.
--
-- A row with unsubscribed_at IS NULL is "currently subscribed". The partial
-- UNIQUE index serialises duplicate active subscriptions to the same feed at
-- the DB boundary; the Telegram handler enforces the per-user cap of 5
-- active subscriptions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_signal_subscriptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feed_id             UUID NOT NULL REFERENCES signal_feeds(id) ON DELETE CASCADE,
    subscribed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unsubscribed_at     TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_signal_subscriptions_active
    ON user_signal_subscriptions (user_id, feed_id)
    WHERE unsubscribed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_user_signal_subscriptions_user_active
    ON user_signal_subscriptions (user_id)
    WHERE unsubscribed_at IS NULL;
