-- Migration 062: add active_preset to positions
-- Stores which strategy preset was active when the position was opened so the
-- WebTrader portfolio can display the correct label (Close Sweep / Safe Close /
-- Flip Hunter / etc.) instead of the generic strategy_type class name.
-- NULL for positions opened before this migration (display falls back to strategy_type).

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS active_preset TEXT DEFAULT NULL;
