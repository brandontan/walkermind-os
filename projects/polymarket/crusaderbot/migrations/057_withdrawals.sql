-- 057: withdrawals table + withdrawal_approval_mode system setting
--
-- paper-only; no on-chain transfer yet — architecture ready for live activation.
-- approval_mode: 'manual' = admin must approve; 'auto' = auto-approve immediately.

CREATE TABLE IF NOT EXISTS withdrawals (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount_usdc         NUMERIC(18,6) NOT NULL CHECK (amount_usdc > 0),
    destination_address VARCHAR(42) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected', 'processing', 'completed', 'failed')),
    approval_mode       VARCHAR(10) NOT NULL DEFAULT 'manual'
                            CHECK (approval_mode IN ('auto', 'manual')),
    admin_notes         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_withdrawals_user_id ON withdrawals (user_id);
CREATE INDEX IF NOT EXISTS idx_withdrawals_status  ON withdrawals (status) WHERE status = 'pending';

-- RLS: authenticated users can only see their own withdrawals
ALTER TABLE withdrawals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS withdrawals_user_select ON withdrawals;
CREATE POLICY withdrawals_user_select ON withdrawals
    FOR SELECT
    USING (auth.uid()::text = user_id::text);

-- Seed withdrawal_approval_mode into system_settings (default: manual)
INSERT INTO system_settings (key, value)
VALUES ('withdrawal_approval_mode', 'manual')
ON CONFLICT (key) DO NOTHING;
