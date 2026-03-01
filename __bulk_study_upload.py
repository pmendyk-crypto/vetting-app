import sqlite3
import requests
from collections import Counter

BASE = 'https://lumosradflow-h0dggngdg8a2hgbd.ukwest-01.azurewebsites.net'
USER = 'superadmin'
PASS = 'admin111'

# Read source presets from local test DB
con = sqlite3.connect('hub.db')
cur = con.cursor()
rows = cur.execute("SELECT modality, description FROM study_description_presets ORDER BY modality, description").fetchall()
con.close()
print('SOURCE_ROWS', len(rows))

# Login to live
s = requests.Session()
r = s.post(f'{BASE}/login', data={'username': USER, 'password': PASS}, allow_redirects=False, timeout=60)
print('LOGIN_STATUS', r.status_code, 'LOCATION', r.headers.get('Location'))
if r.status_code not in (302, 303):
    raise SystemExit('Login failed, aborting bulk upload')

added = 0
failed = 0
for i, (modality, description) in enumerate(rows, 1):
    try:
        resp = s.post(
            f'{BASE}/settings/study-descriptions/add',
            data={'modality': modality, 'description': description},
            allow_redirects=False,
            timeout=60,
        )
        if resp.status_code in (302, 303):
            added += 1
        else:
            failed += 1
        if i % 100 == 0:
            print('PROGRESS', i, 'ADDED', added, 'FAILED', failed)
    except Exception:
        failed += 1

print('UPLOAD_DONE', 'ADDED', added, 'FAILED', failed)

# Verify counts by modality from live API
counts = {}
for m in ['CT', 'MRI', 'XR', 'PET', 'DEXA']:
    rr = s.get(f'{BASE}/api/study-descriptions/by-modality/{m}?org_id=1', timeout=60)
    data = rr.json() if rr.status_code == 200 else []
    counts[m] = len(data)

print('LIVE_COUNTS', counts)
print('LIVE_TOTAL', sum(counts.values()))
