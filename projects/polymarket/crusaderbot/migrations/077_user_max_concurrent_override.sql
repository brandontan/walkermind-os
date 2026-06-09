-- migration 077 — per-user concurrent-trades override (Lane WARP/ROOT/concurrency-policy)
--
-- Adds ``user_settings.max_concurrent_override``: the maximum number of
-- concurrent open positions the user permits at any one time. NULL means
-- "use the risk profile default" (conservative=5 / balanced=12 / aggressive=20 /
-- custom=12). When set, gate step 7 (and resume_safety_check step 7) evaluate
-- ``min(profile_default, user_override)`` — the user can ONLY tighten, never
-- loosen, the profile cap. This is the same most-restrictive semantics used by
-- ``daily_loss_override`` and ``max_drawdown_pct``.
--
-- Hard bounds: 1 ≤ v ≤ 20 (1 = "no concurrency, single position only";
-- 20 = the aggressive-profile ceiling — no user may exceed it). Values
-- outside this range are rejected at the DB layer; the per-profile most-
-- restrictive selection happens at the gate.
--
-- Default NULL — safe-by-default. Existing users see no behaviour change
-- until they explicitly opt to tighten.
--
-- Additive, idempotent, no data backfill required.

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS max_concurrent_override INTEGER
    CHECK (max_concurrent_override IS NULL
           OR (max_concurrent_override >= 1 AND max_concurrent_override <= 20));

COMMENT ON COLUMN user_settings.max_concurrent_override IS
  'Per-user override for max concurrent open positions (1..20). NULL = use '
  'risk-profile default. Gate step 7 picks min(profile_default, this) — '
  'user can only tighten, never loosen, the profile cap.';
