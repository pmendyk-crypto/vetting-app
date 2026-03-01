#!/usr/bin/env python3
"""Create superadmin user in database"""
import os
import sys

# Set DATABASE_URL if you're importing from Azure
# os.environ['DATABASE_URL'] = 'your_postgres_url'

from app.main import ensure_superadmin_user, get_db

try:
    print("Creating/updating superadmin user...")
    ensure_superadmin_user()
    print("✓ Superadmin user created/updated successfully")
    
    # Verify
    conn = get_db()
    row = conn.execute("SELECT username, is_superuser, is_active FROM users WHERE username = 'superadmin'").fetchone()
    conn.close()
    
    if row:
        user_dict = dict(row)
        print(f"\nSuperadmin user details:")
        print(f"  Username: {user_dict['username']}")
        print(f"  Is Superuser: {user_dict['is_superuser']}")
        print(f"  Is Active: {user_dict['is_active']}")
        print(f"\nYou can now login with:")
        print(f"  Username: superadmin")
        print(f"  Password: admin 111")
    else:
        print("❌ Superadmin user not found after creation")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
