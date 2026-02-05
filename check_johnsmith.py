#!/usr/bin/env python
import sqlite3

conn = sqlite3.connect('hub.db')
conn.row_factory = sqlite3.Row

# Check johnsmith user
johnsmith = conn.execute(
    "SELECT id, username, first_name, surname FROM users WHERE username = ?",
    ('Johnsmith',)
).fetchone()

if johnsmith:
    print(f"User found: {dict(johnsmith)}")
    
    # Check memberships
    memberships = conn.execute(
        "SELECT * FROM memberships WHERE user_id = ?",
        (johnsmith['id'],)
    ).fetchall()
    print(f"\nMemberships:")
    for m in memberships:
        print(f"  {dict(m)}")
    
    # Check radiologist_profiles
    profiles = conn.execute(
        "SELECT * FROM radiologist_profiles WHERE user_id = ?",
        (johnsmith['id'],)
    ).fetchall()
    print(f"\nRadiologist Profiles:")
    for p in profiles:
        print(f"  {dict(p)}")
else:
    print("Johnsmith not found")

conn.close()
