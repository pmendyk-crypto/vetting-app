#!/usr/bin/env python3
"""Initialize superadmin user in Azure PostgreSQL database"""
import os
import sys

# Set the Azure DATABASE_URL
os.environ['DATABASE_URL'] = 'postgresql+psycopg2://pgadminlumos:Polonez1%21@lumosradflow.postgres.database.azure.com:5432/vetting_app?sslmode=require'

print("Connecting to Azure PostgreSQL...")
print("Database: vetting_app")
print("Host: lumosradflow.postgres.database.azure.com\n")

try:
    from app.main import get_db, ensure_superadmin_user
    
    # Test connection
    print("Testing database connection...")
    conn = get_db()
    
    # Check if users table exists
    try:
        result = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        print(f"✓ Connected! Users table has {result[0] if result else 0} rows\n")
    except Exception as e:
        print(f"⚠ Users table might not exist yet: {e}\n")
    
    conn.close()
    
    # Create/update superadmin user
    print("Creating/updating superadmin user...")
    ensure_superadmin_user()
    print("✓ Superadmin user created/updated successfully!\n")
    
    # Verify
    print("Verifying superadmin user...")
    conn = get_db()
    row = conn.execute("SELECT username, email, is_superuser, is_active FROM users WHERE username = 'superadmin'").fetchone()
    conn.close()
    
    if row:
        user_dict = dict(row)
        print("✓ Superadmin user verified:")
        print(f"  Username: {user_dict.get('username')}")
        print(f"  Email: {user_dict.get('email')}")
        print(f"  Is Superuser: {user_dict.get('is_superuser')}")
        print(f"  Is Active: {user_dict.get('is_active')}")
        print("\n" + "="*50)
        print("SUCCESS! You can now login with:")
        print("  Username: superadmin")
        print("  Password: admin 111")
        print("="*50)
    else:
        print("❌ Superadmin user not found after creation")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
