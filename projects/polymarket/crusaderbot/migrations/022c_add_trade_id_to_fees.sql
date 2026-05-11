-- 022c: Add missing trade_id column to fees table
-- Missed in 022b recovery. Matches original 022 design: UUID FK to positions.

ALTER TABLE fees ADD COLUMN IF NOT EXISTS trade_id UUID REFERENCES positions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_fees_trade_id ON fees(trade_id);
