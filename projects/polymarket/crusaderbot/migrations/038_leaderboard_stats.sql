BEGIN;

CREATE TABLE IF NOT EXISTS leaderboard_stats (
    wallet       VARCHAR(42) PRIMARY KEY,
    alias        VARCHAR(100),
    win_rate     NUMERIC(5,4),
    total_pnl    NUMERIC(18,6),
    volume_usdc  NUMERIC(18,6),
    roi_pct      NUMERIC(8,4),
    badge        VARCHAR(50),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO leaderboard_stats (wallet, alias, win_rate, total_pnl, volume_usdc, roi_pct, badge)
VALUES
    ('0x1111111111111111111111111111111111111111', 'Bull Whale',    0.7600, 12500.00, 82000.00, 0.1524, 'Whale'),
    ('0x2222222222222222222222222222222222222222', 'Hot Steaker',   0.8300,  4200.00, 28000.00, 0.1500, 'Hot Streak'),
    ('0x3333333333333333333333333333333333333333', 'Safe Trader',   0.7100,  3100.00, 41000.00, 0.0756, 'Conservative'),
    ('0x4444444444444444444444444444444444444444', 'Degen Alpha',   0.6200,  8900.00, 61000.00, 0.1460, 'Whale'),
    ('0x5555555555555555555555555555555555555555', 'Steady Wins',   0.7800,  2300.00, 18000.00, 0.1278, 'Conservative')
ON CONFLICT DO NOTHING;

COMMIT;
