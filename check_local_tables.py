import sqlite3
conn = sqlite3.connect(r'c:\Users\pmend\project\Vetting app\hub.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]
print("LOCAL DATABASE TABLES:")
print("\n".join(tables))

# Check for modified_at column in institutions table
cursor.execute("PRAGMA table_info(institutions)")
columns = cursor.fetchall()
print("\n\nINSTITUTIONS TABLE COLUMNS:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

conn.close()
