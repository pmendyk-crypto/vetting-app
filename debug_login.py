#!/usr/bin/env python3
"""Debug login process for superadmin"""
import os
from app.main import verify_user, hash_password
import secrets

# Test verify_user function directly
print("Testing verify_user('superadmin', 'admin 111')...")
result = verify_user("superadmin", "admin 111")

if result:
    print("✓ verify_user() returned a result:")
    for key, value in result.items():
        print(f"  {key}: {value}")
else:
    print("❌ verify_user() returned None")
    
    # Manual debug
    print("\n--- Manual Debug ---")
    from app.main import get_db
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", ("superadmin",)).fetchone()
    conn.close()
    
    if row:
        user_dict = dict(row)
        print(f"User found: {user_dict}")
        
        # Try to get password hash
        try:
            pw = row["password_hash"]
            print(f"✓ password_hash column exists: {pw[:20]}...")
        except (KeyError, TypeError):
            print("❌ password_hash column not found")
            try:
                pw = row["pw_hash_hex"]
                print(f"✓ pw_hash_hex column exists: {pw[:20]}...")
            except (KeyError, TypeError):
                print("❌ pw_hash_hex column not found either")
        
        # Check salt
        try:
            salt_hex = row["salt_hex"]
            print(f"✓ salt_hex exists: {salt_hex[:20]}...")
            salt = bytes.fromhex(salt_hex)
            
            # Test hash
            provided = hash_password("admin 111", salt)
            print(f"  Computed hash: {provided.hex()[:20]}...")
        except Exception as e:
            print(f"❌ Error: {e}")
    else:
        print("❌ User not found")
