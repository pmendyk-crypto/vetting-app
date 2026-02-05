import sqlite3

conn = sqlite3.connect('hub.db')
cursor = conn.cursor()

print("=== Protocols table structure ===")
cursor.execute("PRAGMA table_info(protocols)")
for col in cursor.fetchall():
    print(f"  {col[1]} ({col[2]})")

print("\n=== Sample protocols ===")
cursor.execute("SELECT * FROM protocols LIMIT 3")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT * FROM protocols LIMIT 3")
for row in cursor.fetchall():
    print(dict(row))

conn.close()
