import sqlite3
import requests

BASE = 'https://lumosradflow-h0dggngdg8a2hgbd.ukwest-01.azurewebsites.net'
USER = 'superadmin'
PASS = 'admin111'

con = sqlite3.connect('hub.db')
rows = con.execute("SELECT modality, description FROM study_description_presets ORDER BY modality, description").fetchall()
con.close()
print('SOURCE', len(rows), flush=True)

s = requests.Session()
r = s.post(f'{BASE}/login', data={'username': USER, 'password': PASS}, allow_redirects=False, timeout=60)
print('LOGIN', r.status_code, r.headers.get('Location',''), flush=True)
if r.status_code not in (302, 303):
    raise SystemExit('LOGIN_FAILED')

ok = 0
for i, (m, d) in enumerate(rows, 1):
    rr = s.post(
        f'{BASE}/settings/study-descriptions/add',
        data={'modality': str(m).strip().upper(), 'description': str(d).strip()},
        allow_redirects=False,
        timeout=60,
    )
    if rr.status_code in (302, 303):
        ok += 1
    if i % 200 == 0:
        print('PROGRESS', i, 'OK', ok, flush=True)

print('UPLOAD_OK', ok, flush=True)

tot = 0
for mod in ['CT','MRI','XR','PET','DEXA']:
    x = s.get(f'{BASE}/api/study-descriptions/by-modality/{mod}?org_id=1', timeout=60)
    data = x.json() if x.status_code == 200 else []
    c = len(data)
    tot += c
    print(f'{mod}={c}', flush=True)
print('TOTAL', tot, flush=True)
