import sqlite3
conn = sqlite3.connect('hub.db')
cur = conn.cursor()
cur.execute("INSERT OR REPLACE INTO radiologists(name,email,surname,gmc) VALUES(?,?,?,?)",
            ('E2E Rad','e2e@example.com','E2E','12345'))
conn.commit()
cur.execute("SELECT name,email,surname,gmc FROM radiologists WHERE name=?",('E2E Rad',))
print(cur.fetchone())
conn.close()