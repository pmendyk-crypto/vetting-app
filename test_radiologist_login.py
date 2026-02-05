#!/usr/bin/env python
import sqlite3
import hashlib
import secrets
from app.main import verify_user, get_db

# Test the verify_user function with johnsmith
username = "Johnsmith"
password = "password123"  # Use the actual password for johnsmith

print(f"Testing verify_user with username={username}")
result = verify_user(username, password)

if result:
    print(f"✓ Login successful!")
    print(f"  User ID: {result.get('id')}")
    print(f"  Username: {result.get('username')}")
    print(f"  Role: {result.get('role')}")
    print(f"  First Name: {result.get('first_name')}")
    print(f"  Surname: {result.get('surname')}")
    print(f"  Radiologist Name: {result.get('radiologist_name')}")
    
    # Now simulate what require_radiologist does
    print("\nSimulating require_radiologist lookup:")
    user_id = result.get('id')
    
    conn = get_db()
    rad_profile = conn.execute(
        "SELECT display_name FROM radiologist_profiles WHERE user_id = ? LIMIT 1",
        (user_id,)
    ).fetchone()
    conn.close()
    
    if rad_profile:
        print(f"Found radiologist_profiles: {rad_profile}")
        if isinstance(rad_profile, dict):
            display_name = rad_profile.get("display_name")
        else:
            display_name = rad_profile[0] if isinstance(rad_profile, (list, tuple)) else str(rad_profile)
        print(f"Display name: {display_name}")
    else:
        print("No radiologist_profiles found")
else:
    print(f"✗ Login failed!")
    
    # Check if user exists
    conn = get_db()
    user_row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    
    if user_row:
        print(f"User exists: {user_row}")
    else:
        print(f"User does not exist")
