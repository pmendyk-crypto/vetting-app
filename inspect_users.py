import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "hub.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("Current users table structure:")
cur.execute("PRAGMA table_info(users)")
for row in cur.fetchall():
    print(f"  {row[1]} ({row[2]})")

print("\nSample user (if any):")
cur.execute("SELECT * FROM users LIMIT 1")
row = cur.fetchone()
if row:
    cur.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cur.fetchall()]
    for col, val in zip(columns, row):
        print(f"  {col}: {val}")

conn.close()
