-- migration 078 — link the two legs of a complete-set arbitrage position
--
-- Lane: WARP/ROOT/complete-set-arb-lane2 (MAJOR — execution chain foundation)
--
-- A complete-set arb buys BOTH outcome legs (YES + NO) of one binary market so
-- the pair settles to a locked $1.00/share. Each leg is still its own row in
-- `positions` (its own order, fill, exit), but the two rows must reference each
-- other so the engine, risk gate, exit watcher, and UI can treat them as ONE
-- economic unit (size = combined set cost, not 2x a side; redeem settles both).
--
-- `paired_position_id` is the self-referential link: leg A points at leg B and
-- leg B points at leg A (both set inside the same booking transaction in Lane
-- 2B). NULL for every existing row and every single-leg (directional) position,
-- so this column is additive and changes no current behaviour.
--
-- ON DELETE SET NULL (not CASCADE): deleting/cleaning one leg must never cascade
-- into silently deleting its sibling — the surviving leg is unlinked, not
-- destroyed. The partial index supports the sibling lookup the exit/UI paths do.

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS paired_position_id UUID
    REFERENCES positions(id) ON DELETE SET NULL DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_positions_paired
  ON positions(paired_position_id)
  WHERE paired_position_id IS NOT NULL;
