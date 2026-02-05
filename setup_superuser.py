#!/usr/bin/env python3
"""Quick setup: Create default superuser"""

import sqlite3
import hashlib
import secrets
from pathlib import Path

DB_PATH = Path(__file__).parent / "hub.db"

def hash_password(password: str, salt_hex: str) -> str:
    salt_bytes = bytes.fromhex(salt_hex)
    pw_bytes = password.encode('utf-8')
    combined = salt_bytes + pw_bytes
    return hashlib.sha256(combined).hexdigest()

# Default superuser credentials
USERNAME = "admin"
EMAIL = "admin@vetapp.com"
PASSWORD = "Admin123!"  # Change this after first login!

print("=" * 60)
print("🔐 CREATING DEFAULT SUPERUSER")
print("=" * 60)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check if users table exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
if not cur.fetchone():
    print("\n❌ Multi-tenant tables not found!")
    print("Run migration first:")
    print("  sqlite3 hub.db < database/migrations/001_add_multi_tenant_schema.sql")
    print("  python scripts/migrate_to_multitenant.py")
    exit(1)

# Generate salt and hash
salt_hex = secrets.token_hex(16)
pw_hash_hex = hash_password(PASSWORD, salt_hex)

# Check if user exists
cur.execute("SELECT id FROM users WHERE username = ?", (USERNAME,))
existing = cur.fetchone()

if existing:
    # Update to superuser
    cur.execute("""
        UPDATE users 
        SET email = ?, password_hash = ?, salt_hex = ?, 
            is_superuser = 1, is_active = 1, modified_at = datetime('now')
        WHERE username = ?
    """, (EMAIL, pw_hash_hex, salt_hex, USERNAME))
    print(f"\n✅ Updated '{USERNAME}' to superuser")
else:
    # Create new
    cur.execute("""
        INSERT INTO users (username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at)
        VALUES (?, ?, ?, ?, 1, 1, datetime('now'), datetime('now'))
    """, (USERNAME, EMAIL, pw_hash_hex, salt_hex))
    print(f"\n✅ Created superuser '{USERNAME}'")

conn.commit()

# Display info
cur.execute("SELECT id, username, email FROM users WHERE username = ?", (USERNAME,))
user = cur.fetchone()

print("\n" + "=" * 60)
print("✅ SUPERUSER READY")
print("=" * 60)
print(f"Username:   {user['username']}")
print(f"Password:   {PASSWORD}")
print(f"Email:      {user['email']}")
print("=" * 60)

print("\n🚀 Access Multi-Tenant Features:")
print(f"1. Login: http://127.0.0.1:8000/login")
print(f"2. Organisations: http://127.0.0.1:8000/superuser/organisations")
print(f"3. Manage Users: http://127.0.0.1:8000/superuser/organisations/1/members")
print("\n⚠️  IMPORTANT: Change the password after first login!")
print("=" * 60)

conn.close()
