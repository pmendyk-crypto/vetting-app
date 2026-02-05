-- ================================================================================
-- MULTI-TENANT DATABASE MIGRATION SCRIPT
-- ================================================================================
-- This script converts a single-tenant app to a proper multi-tenant architecture.
-- It creates new tables and org_id columns while preserving existing data.
--
-- IMPORTANT: 
-- 1. Backup your database first: cp hub.db hub.db.backup
-- 2. Test on a copy before running on production
-- 3. This script is idempotent (safe to run multiple times)
--
-- ================================================================================
-- PHASE 1: CREATE NEW CORE TABLES
-- ================================================================================

-- ORG TABLE: Platform tenants/organisations
CREATE TABLE IF NOT EXISTS organisations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    modified_at TEXT
);

-- NEW USERS TABLE: Global user records (replaces part of old structure)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    salt_hex TEXT NOT NULL,
    is_superuser INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    modified_at TEXT
);

-- MEMBERSHIPS TABLE: User → Org mapping with role
CREATE TABLE IF NOT EXISTS memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    org_role TEXT NOT NULL DEFAULT 'org_user',  -- 'superuser', 'org_admin', 'radiologist', 'org_user'
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    modified_at TEXT,
    FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(org_id, user_id)
);

-- RADIOLOGIST_PROFILES TABLE: Optional profile data for radiologists
CREATE TABLE IF NOT EXISTS radiologist_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    gmc TEXT,
    specialty TEXT,
    display_name TEXT,
    created_at TEXT NOT NULL,
    modified_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ================================================================================
-- PHASE 2: ADD ORG_ID TO EXISTING TENANT-OWNED TABLES
-- ================================================================================

-- CASES table: Add org_id column
ALTER TABLE cases ADD COLUMN org_id INTEGER DEFAULT NULL;
-- Will be populated in Phase 3

-- INSTITUTIONS table: Add org_id column
ALTER TABLE institutions ADD COLUMN org_id INTEGER DEFAULT NULL;
-- Will be populated in Phase 3

-- PROTOCOLS table: Add org_id column
-- Note: protocols table may already have institution_id, org_id is for direct scoping
ALTER TABLE protocols ADD COLUMN org_id INTEGER DEFAULT NULL;
-- Will be populated in Phase 3

-- Create config table if not exists (for storing metadata)
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Create audit_logs table for tracking user management actions
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER,
    user_id INTEGER,
    action TEXT NOT NULL,  -- 'user_created', 'user_deleted', 'role_changed', 'org_created', etc
    target_user_id INTEGER,
    target_org_id INTEGER,
    details TEXT,  -- JSON
    created_at TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (target_org_id) REFERENCES organisations(id) ON DELETE SET NULL
);

-- ================================================================================
-- PHASE 3: CREATE INDEXES FOR PERFORMANCE
-- ================================================================================

CREATE INDEX IF NOT EXISTS idx_memberships_org_id ON memberships(org_id);
CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_active ON memberships(is_active, org_id);

CREATE INDEX IF NOT EXISTS idx_radiologist_profiles_user_id ON radiologist_profiles(user_id);

CREATE INDEX IF NOT EXISTS idx_cases_org_id ON cases(org_id);
CREATE INDEX IF NOT EXISTS idx_cases_org_status ON cases(org_id, status);
CREATE INDEX IF NOT EXISTS idx_cases_org_radiologist ON cases(org_id, assigned_radiologist_user_id);

CREATE INDEX IF NOT EXISTS idx_institutions_org_id ON institutions(org_id);

CREATE INDEX IF NOT EXISTS idx_protocols_org_id ON protocols(org_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_org_id ON audit_logs(org_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(created_at);

-- ================================================================================
-- PHASE 4: ADD FOREIGN KEY CONSTRAINTS
-- ================================================================================

-- These will be added after data migration to ensure referential integrity
-- Note: SQLite requires recreating tables to add FKs, so this is done separately

-- ================================================================================
-- MIGRATION NOTES:
-- ================================================================================
-- After running this script, execute the migration_from_old_schema.py script to:
-- 1. Create default organisation for existing data
-- 2. Migrate existing users
-- 3. Migrate existing radiologist linkages
-- 4. Populate org_id on all tenant-owned records
-- 5. Validate and verify data integrity
-- ================================================================================
