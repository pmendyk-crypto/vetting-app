import sqlite3

conn = sqlite3.connect('hub.db')
conn.row_factory = sqlite3.Row

# Check table exists
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
preset_tables = [t for t in tables if 'preset' in t.lower()]
print('Tables:', preset_tables)

# Count presets by modality
modality_counts = conn.execute("SELECT modality, COUNT(*) as count FROM study_description_presets GROUP BY modality ORDER BY count DESC").fetchall()
print('\n📊 Study Descriptions Loaded:')
for row in modality_counts:
    print(f'  {row[0]}: {row[1]} presets')

total = sum([r[1] for r in modality_counts])
print(f'\n✅ Total: {total} presets loaded')

# Show sample presets
print('\n📋 Sample Presets (first 3 per modality):')
for modality in ['CT', 'MRI', 'XR', 'DEXA', 'PET']:
    samples = conn.execute("SELECT description FROM study_description_presets WHERE modality = ? LIMIT 3", (modality,)).fetchall()
    if samples:
        print(f'  {modality}:')
        for s in samples:
            print(f'    - {s[0]}')

conn.close()
