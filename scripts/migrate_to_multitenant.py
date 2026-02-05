#!/usr/bin/env python3
"""
Migration script: Convert from single-tenant to multi-tenant schema.

IMPORTANT: Backup your database before running this!
    cp hub.db hub.db.backup

Usage:
    python migrate_to_multitenant.py

This script will:
1. Create a default organisation for existing data
2. Migrate existing users
3. Migrate existing radiologist records
4. Set org_id on all existing records
5. Validate data integrity
6. Generate a migration report
"""

import sqlite3
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional


class Migration:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.conn = None
        self.report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "errors": [],
            "warnings": [],
            "summary": {}
        }
    
    def log_error(self, msg: str):
        """Log an error."""
        print(f"❌ ERROR: {msg}")
        self.report["errors"].append(msg)
    
    def log_warning(self, msg: str):
        """Log a warning."""
        print(f"⚠️  WARNING: {msg}")
        self.report["warnings"].append(msg)
    
    def log_info(self, msg: str):
        """Log info message."""
        print(f"ℹ️  {msg}")
    
    def log_success(self, msg: str):
        """Log success message."""
        print(f"✓ {msg}")
    
    def connect(self):
        """Connect to database."""
        if not self.db_path.exists():
            self.log_error(f"Database not found: {self.db_path}")
            sys.exit(1)
        
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.log_success(f"Connected to database: {self.db_path}")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
    
    def table_exists(self, table_name: str) -> bool:
        """Check if table exists."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return cursor.fetchone() is not None
    
    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if column exists in table."""
        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1] for row in cursor.fetchall()}
        return column_name in columns
    
    def get_utc_now_iso(self) -> str:
        """Get current UTC time in ISO format."""
        return datetime.now(timezone.utc).isoformat()
    
    def phase1_create_core_tables(self):
        """Phase 1: Create new core tables if they don't exist."""
        self.log_info("\n=== PHASE 1: Creating core multi-tenant tables ===")
        
        try:
            cursor = self.conn.cursor()
            
            # Create organisations table
            if not self.table_exists("organisations"):
                cursor.execute("""
                    CREATE TABLE organisations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        slug TEXT NOT NULL UNIQUE,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        modified_at TEXT
                    )
                """)
                self.log_success("Created organisations table")
            
            # Create new users table (replacing old one)
            if not self.table_exists("users_new"):
                cursor.execute("""
                    CREATE TABLE users_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        email TEXT UNIQUE,
                        password_hash TEXT NOT NULL,
                        salt_hex TEXT NOT NULL,
                        is_superuser INTEGER NOT NULL DEFAULT 0,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        modified_at TEXT
                    )
                """)
                self.log_success("Created new users table (users_new)")
            
            # Create memberships table
            if not self.table_exists("memberships"):
                cursor.execute("""
                    CREATE TABLE memberships (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        org_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        org_role TEXT NOT NULL DEFAULT 'org_user',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        modified_at TEXT,
                        FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users_new(id) ON DELETE CASCADE,
                        UNIQUE(org_id, user_id)
                    )
                """)
                self.log_success("Created memberships table")
            
            # Create radiologist_profiles table
            if not self.table_exists("radiologist_profiles"):
                cursor.execute("""
                    CREATE TABLE radiologist_profiles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL UNIQUE,
                        gmc TEXT,
                        specialty TEXT,
                        display_name TEXT,
                        created_at TEXT NOT NULL,
                        modified_at TEXT,
                        FOREIGN KEY (user_id) REFERENCES users_new(id) ON DELETE CASCADE
                    )
                """)
                self.log_success("Created radiologist_profiles table")
            
            # Create audit_logs table
            if not self.table_exists("audit_logs"):
                cursor.execute("""
                    CREATE TABLE audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        org_id INTEGER,
                        user_id INTEGER,
                        action TEXT NOT NULL,
                        target_user_id INTEGER,
                        target_org_id INTEGER,
                        details TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE SET NULL,
                        FOREIGN KEY (user_id) REFERENCES users_new(id) ON DELETE SET NULL
                    )
                """)
                self.log_success("Created audit_logs table")
            
            self.conn.commit()
            self.report["summary"]["phase1"] = "Core tables created"
            
        except Exception as e:
            self.log_error(f"Failed to create core tables: {e}")
            self.report["status"] = "failed"
            raise
    
    def phase2_add_org_id_columns(self):
        """Phase 2: Add org_id columns to existing tables."""
        self.log_info("\n=== PHASE 2: Adding org_id columns to existing tables ===")
        
        tables_to_scope = [
            ("cases", "Cases"),
            ("institutions", "Institutions"),
            ("protocols", "Protocols"),
        ]
        
        cursor = self.conn.cursor()
        
        for table_name, display_name in tables_to_scope:
            if not self.table_exists(table_name):
                self.log_warning(f"Table {table_name} does not exist, skipping")
                continue
            
            if self.column_exists(table_name, "org_id"):
                self.log_info(f"{display_name} already has org_id column")
                continue
            
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN org_id INTEGER DEFAULT NULL")
                self.log_success(f"Added org_id column to {table_name}")
            except Exception as e:
                self.log_error(f"Failed to add org_id to {table_name}: {e}")
                raise
        
        self.conn.commit()
        self.report["summary"]["phase2"] = "org_id columns added"
    
    def phase3_create_default_org(self):
        """Phase 3: Create default organisation and migrate existing data."""
        self.log_info("\n=== PHASE 3: Creating default organisation ===")
        
        cursor = self.conn.cursor()
        now = self.get_utc_now_iso()
        
        # Check if default org already exists
        cursor.execute("SELECT id FROM organisations WHERE slug = 'default'")
        existing = cursor.fetchone()
        
        if existing:
            self.log_info("Default organisation already exists")
            default_org_id = existing[0]
        else:
            # Create default org
            cursor.execute("""
                INSERT INTO organisations (name, slug, is_active, created_at)
                VALUES ('Default Organisation', 'default', 1, ?)
            """, (now,))
            self.conn.commit()
            default_org_id = cursor.lastrowid
            self.log_success(f"Created default organisation (org_id={default_org_id})")
        
        self.report["summary"]["default_org_id"] = default_org_id
        return default_org_id
    
    def phase4_migrate_users(self, default_org_id: int):
        """Phase 4: Migrate existing users to new schema."""
        self.log_info("\n=== PHASE 4: Migrating users ===")
        
        cursor = self.conn.cursor()
        now = self.get_utc_now_iso()
        
        if not self.table_exists("users"):
            self.log_warning("Old users table does not exist")
            return 0
        
        # Get all users from old table
        # Note: old table uses pw_hash_hex, new table uses password_hash
        cursor.execute("""
            SELECT username, pw_hash_hex as password_hash, salt_hex, email, role
            FROM users
        """)
        old_users = cursor.fetchall()
        
        if not old_users:
            self.log_info("No users to migrate")
            return 0
        
        migrated_count = 0
        
        for old_user in old_users:
            username = old_user["username"]
            password_hash = old_user["password_hash"]
            salt_hex = old_user["salt_hex"]
            email = old_user["email"] if old_user["email"] else f"{username}@example.com"
            is_active = 1  # Default to active
            old_role = old_user["role"] if old_user["role"] else "user"
            old_created_at = now
            
            # Determine if this user should be superuser
            # Migrate 'admin' role to superuser if they have global admin permissions
            is_superuser = (old_role.lower() == "admin")
            
            try:
                # Insert into new users table
                cursor.execute("""
                    INSERT OR IGNORE INTO users_new
                    (username, email, password_hash, salt_hex, is_superuser, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (username, email, password_hash, salt_hex, 1 if is_superuser else 0, is_active, old_created_at))
                
                if cursor.rowcount > 0:
                    new_user_id = cursor.lastrowid
                    
                    # Create membership in default org
                    # Use org_role based on old role
                    org_role = "org_admin" if old_role.lower() == "admin" else "org_user"
                    
                    cursor.execute("""
                        INSERT OR IGNORE INTO memberships
                        (org_id, user_id, org_role, is_active, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (default_org_id, new_user_id, org_role, is_active, old_created_at))
                    
                    migrated_count += 1
                    self.log_success(f"Migrated user: {username} (role: {org_role})")
            
            except Exception as e:
                self.log_error(f"Failed to migrate user {username}: {e}")
        
        self.conn.commit()
        self.report["summary"]["users_migrated"] = migrated_count
        self.log_success(f"Total users migrated: {migrated_count}")
        return migrated_count
    
    def phase5_migrate_radiologists(self):
        """Phase 5: Migrate radiologist records to profiles."""
        self.log_info("\n=== PHASE 5: Migrating radiologist records ===")
        
        cursor = self.conn.cursor()
        now = self.get_utc_now_iso()
        
        if not self.table_exists("radiologists"):
            self.log_warning("Radiologists table does not exist")
            return 0
        
        # Get all radiologists
        cursor.execute("""
            SELECT name, email, surname, gmc, speciality
            FROM radiologists
        """)
        old_radiologists = cursor.fetchall()
        
        if not old_radiologists:
            self.log_info("No radiologists to migrate")
            return 0
        
        migrated_count = 0
        
        for old_rad in old_radiologists:
            name = old_rad["name"]
            # Handle nullable columns - check if key exists and is not None
            email = old_rad["email"] if old_rad["email"] else None
            surname = old_rad["surname"] if old_rad["surname"] else None
            gmc = old_rad["gmc"] if old_rad["gmc"] else None
            speciality = old_rad["speciality"] if old_rad["speciality"] else None
            
            try:
                # Find or create user for this radiologist
                cursor.execute(
                    "SELECT id FROM users_new WHERE username = ? OR email = ?",
                    (name, email)
                )
                user_row = cursor.fetchone()
                
                if user_row:
                    user_id = user_row[0]
                else:
                    # Create new user for radiologist
                    # Generate a password hash (should be set by user later)
                    cursor.execute("""
                        INSERT INTO users_new
                        (username, email, password_hash, salt_hex, is_active, created_at)
                        VALUES (?, ?, ?, ?, 1, ?)
                    """, (name, email, "needs_reset", "needs_reset", now))
                    
                    user_id = cursor.lastrowid
                    self.log_info(f"Created new user for radiologist: {name}")
                
                # Create radiologist profile
                display_name = name
                if surname:
                    display_name = f"{name} {surname}"
                
                cursor.execute("""
                    INSERT OR IGNORE INTO radiologist_profiles
                    (user_id, gmc, specialty, display_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, gmc, speciality, display_name, now))
                
                migrated_count += 1
                self.log_success(f"Migrated radiologist: {name}")
            
            except Exception as e:
                self.log_error(f"Failed to migrate radiologist {name}: {e}")
        
        self.conn.commit()
        self.report["summary"]["radiologists_migrated"] = migrated_count
        self.log_success(f"Total radiologists migrated: {migrated_count}")
        return migrated_count
    
    def phase6_populate_org_ids(self, default_org_id: int):
        """Phase 6: Set org_id on all existing tenant records."""
        self.log_info("\n=== PHASE 6: Populating org_id on existing records ===")
        
        cursor = self.conn.cursor()
        
        tables_to_populate = [
            ("cases", "Cases"),
            ("institutions", "Institutions"),
            ("protocols", "Protocols"),
        ]
        
        total_updated = 0
        
        for table_name, display_name in tables_to_populate:
            if not self.table_exists(table_name):
                self.log_warning(f"Table {table_name} does not exist, skipping")
                continue
            
            try:
                # Update records with NULL org_id
                cursor.execute(
                    f"UPDATE {table_name} SET org_id = ? WHERE org_id IS NULL",
                    (default_org_id,)
                )
                
                updated_count = cursor.rowcount
                total_updated += updated_count
                self.log_success(f"Updated {updated_count} {table_name} records with default org_id")
            
            except Exception as e:
                self.log_error(f"Failed to populate org_id for {table_name}: {e}")
        
        self.conn.commit()
        self.report["summary"]["records_org_scoped"] = total_updated
        self.log_success(f"Total records org-scoped: {total_updated}")
    
    def phase7_create_indexes(self):
        """Phase 7: Create indexes for performance."""
        self.log_info("\n=== PHASE 7: Creating indexes ===")
        
        cursor = self.conn.cursor()
        
        indexes = [
            ("idx_memberships_org_id", "CREATE INDEX IF NOT EXISTS idx_memberships_org_id ON memberships(org_id)"),
            ("idx_memberships_user_id", "CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships(user_id)"),
            ("idx_cases_org_id", "CREATE INDEX IF NOT EXISTS idx_cases_org_id ON cases(org_id)"),
            ("idx_institutions_org_id", "CREATE INDEX IF NOT EXISTS idx_institutions_org_id ON institutions(org_id)"),
            ("idx_protocols_org_id", "CREATE INDEX IF NOT EXISTS idx_protocols_org_id ON protocols(org_id)"),
            ("idx_audit_logs_org_id", "CREATE INDEX IF NOT EXISTS idx_audit_logs_org_id ON audit_logs(org_id)"),
        ]
        
        for idx_name, sql in indexes:
            try:
                cursor.execute(sql)
                self.log_success(f"Created index: {idx_name}")
            except Exception as e:
                self.log_warning(f"Failed to create index {idx_name}: {e}")
        
        self.conn.commit()
    
    def phase8_validate_data(self):
        """Phase 8: Validate data integrity."""
        self.log_info("\n=== PHASE 8: Validating data integrity ===")
        
        cursor = self.conn.cursor()
        validation_passed = True
        
        # Check that all organisations exist
        cursor.execute("SELECT COUNT(*) as c FROM organisations")
        org_count = cursor.fetchone()[0]
        self.log_info(f"Total organisations: {org_count}")
        
        # Check that all users migrated
        cursor.execute("SELECT COUNT(*) as c FROM users_new")
        user_count = cursor.fetchone()[0]
        self.log_info(f"Total users (new schema): {user_count}")
        
        # Check that all memberships exist
        cursor.execute("SELECT COUNT(*) as c FROM memberships")
        membership_count = cursor.fetchone()[0]
        self.log_info(f"Total memberships: {membership_count}")
        
        # Check for cases without org_id
        if self.table_exists("cases"):
            cursor.execute("SELECT COUNT(*) as c FROM cases WHERE org_id IS NULL")
            cases_without_org = cursor.fetchone()[0]
            if cases_without_org > 0:
                self.log_error(f"Found {cases_without_org} cases without org_id!")
                validation_passed = False
            else:
                self.log_success("All cases have org_id")
        
        # Check for institutions without org_id
        if self.table_exists("institutions"):
            cursor.execute("SELECT COUNT(*) as c FROM institutions WHERE org_id IS NULL")
            insts_without_org = cursor.fetchone()[0]
            if insts_without_org > 0:
                self.log_error(f"Found {insts_without_org} institutions without org_id!")
                validation_passed = False
            else:
                self.log_success("All institutions have org_id")
        
        if validation_passed:
            self.report["status"] = "success"
            self.log_success("\n✅ Data integrity validation passed!")
        else:
            self.report["status"] = "warning"
            self.log_warning("\n⚠️  Some validation issues found. Review the errors above.")
        
        return validation_passed
    
    def run(self):
        """Run the complete migration."""
        self.log_info("Starting multi-tenant migration...")
        print("=" * 60)
        
        try:
            self.connect()
            
            self.phase1_create_core_tables()
            self.phase2_add_org_id_columns()
            default_org_id = self.phase3_create_default_org()
            self.phase4_migrate_users(default_org_id)
            self.phase5_migrate_radiologists()
            self.phase6_populate_org_ids(default_org_id)
            self.phase7_create_indexes()
            self.phase8_validate_data()
            
            print("\n" + "=" * 60)
            self.log_success("Migration completed successfully!")
            
            # Save report
            report_path = Path(self.db_path.parent) / f"migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_path, "w") as f:
                json.dump(self.report, f, indent=2)
            self.log_success(f"Migration report saved to: {report_path}")
            
            return True
        
        except Exception as e:
            self.log_error(f"Migration failed: {e}")
            self.report["status"] = "failed"
            raise
        
        finally:
            self.close()


if __name__ == "__main__":
    db_path = "hub.db"
    
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║   MULTI-TENANT MIGRATION SCRIPT                             ║
    ║   Convert single-tenant app to multi-tenant architecture    ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    
    print(f"Database: {db_path}")
    print("\n⚠️  IMPORTANT: Backup your database before continuing!")
    print("   cp hub.db hub.db.backup\n")
    
    response = input("Continue with migration? (type 'yes' to confirm): ")
    if response.lower() != "yes":
        print("Migration cancelled.")
        sys.exit(0)
    
    migration = Migration(db_path)
    try:
        migration.run()
    except Exception as e:
        print(f"\n❌ Migration failed with error: {e}")
        sys.exit(1)
