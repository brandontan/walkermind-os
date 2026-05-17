-- migration: 033_risk_caps_audit_log
-- Track D: Risk Caps + Kill Switch — system_flags + audit_log tables

CREATE TABLE IF NOT EXISTS system_flags (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event VARCHAR(100) NOT NULL,
    reason TEXT,
    triggered_by VARCHAR(200),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_event ON audit_log(event);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
