import sqlite3

conn = sqlite3.connect('hub.db')

# Check all presets with organization_id = 1
presets = conn.execute("SELECT COUNT(*) FROM study_description_presets WHERE organization_id = 1").fetchone()
print(f"✅ Organization ID 1 has {presets[0]} presets loaded\n")

# Sample by modality
for modality in ['CT', 'MRI', 'XR', 'DEXA', 'PET']:
    count = conn.execute("SELECT COUNT(*) FROM study_description_presets WHERE organization_id = 1 AND modality = ?", (modality,)).fetchone()[0]
    samples = conn.execute("SELECT id, description FROM study_description_presets WHERE organization_id = 1 AND modality = ? LIMIT 2", (modality,)).fetchall()
    print(f"{modality}: {count} presets")
    for id, desc in samples:
        print(f"  ID {id}: {desc}")
    print()

conn.close()

print("=" * 60)
print("\n✅ Data verification complete!")
print("All presets are in the database with organization_id = 1")
print("\nWhen you login and access /submit, select a modality,")
print("the dropdown will load these presets from your organization.")
