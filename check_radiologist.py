import sqlite3

conn = sqlite3.connect('hub.db')
conn.row_factory = sqlite3.Row

print("=== Users matching 'john' or 'smith' ===")
users = conn.execute(
    "SELECT u.id, u.username, u.first_name, u.surname, m.org_role FROM users u "
    "LEFT JOIN memberships m ON u.id = m.user_id "
    "WHERE u.username LIKE ? OR u.first_name LIKE ? OR u.surname LIKE ?",
    ('%john%', '%john%', '%smith%')
).fetchall()

for row in users:
    print(f"ID: {row['id']}, Username: {row['username']}, Name: {row['first_name']} {row['surname']}, Role: {row['org_role']}")

print("\n=== Check radiologist_profiles for these users ===")
for row in users:
    if row['id']:
        prof = conn.execute(
            "SELECT * FROM radiologist_profiles WHERE user_id = ?",
            (row['id'],)
        ).fetchone()
        if prof:
            print(f"User {row['id']}: {dict(prof)}")
        else:
            print(f"User {row['id']}: NO PROFILE")

conn.close()
