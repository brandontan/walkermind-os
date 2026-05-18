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

COMMIT;
