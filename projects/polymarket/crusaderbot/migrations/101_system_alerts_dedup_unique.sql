-- 101_system_alerts_dedup_unique.sql
-- WARP•R00T finishing (PR #1808): make the confirmed-money WebTrader alert
-- dedup ATOMIC. The prior persist_user_alert_once used check-then-insert
-- (SELECT probe + separate INSERT), leaving a race window where two
-- overlapping deposit/withdrawal job ticks could each insert the same alert —
-- so the "exactly once" claim did not hold under concurrency.
--
-- Fix: a partial UNIQUE index on the per-user money-alert dedup key lets the
-- INSERT use ON CONFLICT DO NOTHING, enforcing exactly-once at the DB layer.
-- Idempotent + additive: no DROP, safe to re-run.

-- Collapse any pre-existing duplicate confirmed-money alerts (from the prior
-- check-then-insert path) so the unique index can be created safely. Keeps the
-- earliest physical row per (user, kind, dedup_key). Rows without a dedup_key
-- (global / non-money alerts) and NULL-user rows are untouched.
DELETE FROM system_alerts a
 USING system_alerts b
 WHERE a.ctid > b.ctid
   AND a.user_id = b.user_id
   AND COALESCE(a.alert_kind, '') = COALESCE(b.alert_kind, '')
   AND a.metadata->>'dedup_key' IS NOT NULL
   AND b.metadata->>'dedup_key' IS NOT NULL
   AND a.metadata->>'dedup_key' = b.metadata->>'dedup_key';

-- Atomic dedup arbiter for persist_user_alert_once. Partial so only per-user
-- money-lifecycle alerts (those carrying a dedup_key) are constrained; all
-- other system_alerts inserts are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS uq_system_alerts_money_dedup
    ON system_alerts (user_id, COALESCE(alert_kind, ''), (metadata->>'dedup_key'))
    WHERE metadata->>'dedup_key' IS NOT NULL;
