-- ================================================================================
-- PASSWORD RESET TOKENS + CASE EVENTS (Postgres)
-- ================================================================================

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL,
    requested_ip TEXT,
    requested_ua TEXT
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user_id ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash);

CREATE TABLE IF NOT EXISTS case_events (
    id SERIAL PRIMARY KEY,
    case_id TEXT NOT NULL,
    org_id INTEGER,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    org_role TEXT,
    decision TEXT,
    protocol TEXT,
    comment TEXT
);

CREATE INDEX IF NOT EXISTS idx_case_events_case_id ON case_events(case_id);
CREATE INDEX IF NOT EXISTS idx_case_events_org_id ON case_events(org_id);
CREATE INDEX IF NOT EXISTS idx_case_events_created_at ON case_events(created_at);
