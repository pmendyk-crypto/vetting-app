#!/usr/bin/env python3
"""
Check database status and optionally run migration
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "hub.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("=" * 60)
print("📊 DATABASE STATUS")
print("=" * 60)

# Get all tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cur.fetchall()]

print(f"\nTables found ({len(tables)}):")
for table in tables:
    print(f"  - {table}")

# Check if multi-tenant tables exist
mt_tables = ['organisations', 'memberships', 'radiologist_profiles', 'audit_logs']
missing = [t for t in mt_tables if t not in tables]

if missing:
    print(f"\n❌ Missing multi-tenant tables: {', '.join(missing)}")
    print("\n🔧 MIGRATION NEEDED")
    print("=" * 60)
    print("The multi-tenant features require database migration.")
    print("\nOption 1 - Using Python (RECOMMENDED):")
    print("  python scripts/migrate_to_multitenant.py")
    print("\nOption 2 - Using SQL manually (if you have sqlite3 CLI):")
    print("  sqlite3 hub.db < database/migrations/001_add_multi_tenant_schema.sql")
    print("=" * 60)
else:
    print("\n✅ All multi-tenant tables exist!")
    
    # Check if users table has new structure
    cur.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cur.fetchall()}
    
    if 'is_superuser' in columns:
        print("✅ Users table has multi-tenant structure")
        
        # Count superusers
        cur.execute("SELECT COUNT(*) FROM users WHERE is_superuser = 1")
        superuser_count = cur.fetchone()[0]
        
        if superuser_count > 0:
            cur.execute("SELECT username, email FROM users WHERE is_superuser = 1")
            print(f"\n👑 Superusers found ({superuser_count}):")
            for row in cur.fetchall():
                print(f"  - {row[0]} ({row[1]})")
            
            print("\n✅ Ready to use multi-tenant features!")
            print("Login at: http://127.0.0.1:8000/login")
            print("Manage orgs: http://127.0.0.1:8000/superuser/organisations")
        else:
            print("\n⚠️  No superuser accounts found!")
            print("Run: python setup_superuser.py")
    else:
        print("⚠️  Users table exists but has old structure")
        print("Run migration: python scripts/migrate_to_multitenant.py")

conn.close()
print("=" * 60)
