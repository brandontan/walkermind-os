-- Persist deposit-scan cursor so restarts don't replay or skip blocks.
CREATE TABLE IF NOT EXISTS chain_cursor (
    name TEXT PRIMARY KEY,
    block_number BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO chain_cursor (name, block_number) VALUES ('usdc_deposits', 0)
ON CONFLICT (name) DO NOTHING;

-- error message column for failed live submits
ALTER TABLE orders ADD COLUMN IF NOT EXISTS error_msg TEXT;
