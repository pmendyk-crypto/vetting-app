#!/usr/bin/env python3
"""
Create a superuser account for multi-tenant management.
Run this script to create or update a superuser.
"""

import sqlite3
import hashlib
import secrets
import sys
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent / "hub.db"

def hash_password(password: str, salt_hex: str) -> str:
    """Hash password with salt using SHA-256"""
    salt_bytes = bytes.fromhex(salt_hex)
    pw_bytes = password.encode('utf-8')
    combined = salt_bytes + pw_bytes
    return hashlib.sha256(combined).hexdigest()

def create_superuser():
    print("=" * 60)
    print("🔐 CREATE SUPERUSER ACCOUNT")
    print("=" * 60)
    
    # Get superuser details
    username = input("\nEnter superuser username (e.g., admin): ").strip()
    if not username:
        print("❌ Username cannot be empty!")
        return
    
    email = input("Enter email address: ").strip()
    if not email:
        print("❌ Email cannot be empty!")
        return
    
    password = input("Enter password (min 8 characters): ").strip()
    if len(password) < 8:
        print("❌ Password must be at least 8 characters!")
        return
    
    # Confirm password
    password_confirm = input("Confirm password: ").strip()
    if password != password_confirm:
        print("❌ Passwords do not match!")
        return
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Check if multi-tenant tables exist
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    users_table = cur.fetchone()
    
    if not users_table:
        print("\n❌ Multi-tenant tables not found!")
        print("Please run the migration first:")
        print("  sqlite3 hub.db < database/migrations/001_add_multi_tenant_schema.sql")
        conn.close()
        return
    
    # Check if username already exists
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    existing = cur.fetchone()
    
    # Generate salt and hash password
    salt_hex = secrets.token_hex(16)
    pw_hash_hex = hash_password(password, salt_hex)
    
    if existing:
        # Update existing user to superuser
        user_id = existing['id']
        cur.execute("""
            UPDATE users 
            SET email = ?,
                password_hash = ?,
                salt_hex = ?,
                is_superuser = 1,
                is_active = 1,
                modified_at = datetime('now')
            WHERE id = ?
        """, (email, pw_hash_hex, salt_hex, user_id))
        
        print(f"\n✅ Updated existing user '{username}' to superuser")
    else:
        # Create new superuser
        cur.execute("""
            INSERT INTO users (username, email, password_hash, salt_hex, is_superuser, is_active, created_at, modified_at)
            VALUES (?, ?, ?, ?, 1, 1, datetime('now'), datetime('now'))
        """, (username, email, pw_hash_hex, salt_hex))
        
        print(f"\n✅ Created new superuser: {username}")
    
    conn.commit()
    
    # Get user info
    cur.execute("SELECT id, username, email, is_superuser FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    
    print("\n" + "=" * 60)
    print("✅ SUPERUSER CREATED SUCCESSFULLY")
    print("=" * 60)
    print(f"User ID:    {user['id']}")
    print(f"Username:   {user['username']}")
    print(f"Email:      {user['email']}")
    print(f"Superuser:  {'Yes' if user['is_superuser'] else 'No'}")
    print("=" * 60)
    
    print("\n🚀 Next Steps:")
    print("1. Restart your app (if running)")
    print("2. Login at: http://127.0.0.1:8000/login")
    print(f"3. Use credentials: {username} / [your password]")
    print("4. Access superuser features:")
    print("   • http://127.0.0.1:8000/superuser/organisations")
    print("   • Create organisations")
    print("   • Manage organisation members")
    print("=" * 60)
    
    conn.close()

if __name__ == "__main__":
    try:
        create_superuser()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
