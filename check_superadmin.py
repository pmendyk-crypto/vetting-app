#!/usr/bin/env python3
"""Check superadmin user in database"""
import os
import sqlite3
from app.main import get_db, hash_password

# Try to get the database
try:
    conn = get_db()
    cur = conn.cursor()
    
    # Check if users table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cur.fetchone():
        print("❌ Users table does not exist!")
        conn.close()
        exit(1)
    
    # Get superadmin user
    cur.execute("SELECT * FROM users WHERE username = 'superadmin'")
    user = cur.fetchone()
    
    if not user:
        print("❌ Superadmin user does NOT exist in database")
        print("\nColumns in users table:")
        cur.execute("PRAGMA table_info(users)")
        for col in cur.fetchall():
            print(f"  - {col[1]} ({col[2]})")
    else:
        print("✓ Superadmin user EXISTS")
        # Convert row to dict
        user_dict = dict(user)
        print(f"  Username: {user_dict.get('username')}")
        print(f"  Email: {user_dict.get('email')}")
        print(f"  Is Superuser: {user_dict.get('is_superuser')}")
        print(f"  Is Active: {user_dict.get('is_active')}")
        print(f"  Password Hash Length: {len(user_dict.get('password_hash', '')) if user_dict.get('password_hash') else 'NULL'}")
        print(f"  Salt Length: {len(user_dict.get('salt_hex', '')) if user_dict.get('salt_hex') else 'NULL'}")
        
        # Test password
        print("\nTesting password 'admin 111':")
        salt_hex = user_dict.get('salt_hex')
        password_hash = user_dict.get('password_hash')
        
        if salt_hex and password_hash:
            try:
                salt = bytes.fromhex(salt_hex)
                provided = hash_password("admin 111", salt)
                expected = bytes.fromhex(password_hash)
                
                import secrets
                if secrets.compare_digest(provided, expected):
                    print("  ✓ Password matches!")
                else:
                    print("  ❌ Password does NOT match")
                    print(f"    Expected hash: {password_hash[:20]}...")
                    print(f"    Got hash:      {provided.hex()[:20]}...")
            except Exception as e:
                print(f"  ❌ Error testing password: {e}")
        else:
            print("  ❌ No salt or password hash found")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
