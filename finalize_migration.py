#!/usr/bin/env python3
"""
Finalize the multi-tenant migration by replacing old users table with new one
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "hub.db"

print("=" * 60)
print("🔄 FINALIZING MULTI-TENANT MIGRATION")
print("=" * 60)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Check if users_new exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users_new'")
if not cur.fetchone():
    print("\n❌ users_new table not found!")
    print("Run the migration first: python scripts/migrate_to_multitenant.py")
    conn.close()
    exit(1)

print("\n1. Backing up old users table to users_old...")
cur.execute("DROP TABLE IF EXISTS users_old")
cur.execute("ALTER TABLE users RENAME TO users_old")
conn.commit()
print("✅ Old users table backed up")

print("\n2. Renaming users_new to users...")
cur.execute("ALTER TABLE users_new RENAME TO users")
conn.commit()
print("✅ New users table activated")

print("\n3. Verifying new structure...")
cur.execute("PRAGMA table_info(users)")
columns = [row[1] for row in cur.fetchall()]
print(f"   Columns: {', '.join(columns)}")

if 'is_superuser' in columns:
    print("✅ New users table has correct structure")
else:
    print("❌ ERROR: Missing expected columns!")
    conn.close()
    exit(1)

print("\n4. Checking for superusers...")
cur.execute("SELECT username, email, is_superuser FROM users WHERE username = 'admin'")
admin = cur.fetchone()

if admin:
    print(f"✅ Found admin user: {admin[0]} ({admin[1]})")
    if admin[2] == 1:
        print("   ✅ Admin is already a superuser")
    else:
        print("   ⚠️  Admin is not a superuser yet")
        cur.execute("UPDATE users SET is_superuser = 1 WHERE username = 'admin'")
        conn.commit()
        print("   ✅ Upgraded admin to superuser")
else:
    print("⚠️  No admin user found - you'll need to create one")

conn.close()

print("\n" + "=" * 60)
print("✅ MIGRATION FINALIZED")
print("=" * 60)
print("\n🚀 Next steps:")
print("1. Restart your app")
print("2. Login with your existing admin credentials")
print("3. Access multi-tenant features:")
print("   http://127.0.0.1:8000/superuser/organisations")
print("=" * 60)
