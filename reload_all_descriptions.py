import csv
import sqlite3

csv_file = r"C:\Users\pmend\OneDrive\Vetting App\Study description preset .csv"

# Parse CSV and extract all data
data = {
    'CT': [],
    'DEXA': []
}

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    headers = next(reader)  # Get headers
    
    # headers = ['CT', '', '', '', 'DEXA']
    
    for row in reader:
        # Column 1 = CT (index 0)
        if len(row) > 0 and row[0].strip():
            data['CT'].append(row[0].strip())
        
        # Column 5 = DEXA (index 4)
        if len(row) > 4 and row[4].strip():
            data['DEXA'].append(row[4].strip())

print("📊 CSV Parsing Results:")
print(f"  CT descriptions: {len(data['CT'])}")
print(f"  DEXA descriptions: {len(data['DEXA'])}")
print(f"  Total: {sum(len(v) for v in data.values())}")

print("\n" + "="*60)
print("✅ Sample CT descriptions:")
for desc in data['CT'][:5]:
    print(f"   - {desc}")

print("\n✅ Sample DEXA descriptions:")
for desc in data['DEXA'][:5]:
    print(f"   - {desc}")

print("\n" + "="*60)
print("\n💾 Clearing old data and loading all descriptions...\n")

# Clear old data and load everything
conn = sqlite3.connect('hub.db')
conn.execute("DELETE FROM study_description_presets WHERE organization_id = 1")

imported = 0
for modality, descriptions in data.items():
    for description in descriptions:
        try:
            conn.execute(
                "INSERT INTO study_description_presets (organization_id, modality, description, created_at, updated_at, created_by) VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)",
                (1, modality, description)
            )
            imported += 1
        except Exception as e:
            print(f"⚠️  Skipped duplicate: {modality} - {description}")

conn.commit()

# Verify
final_count = conn.execute("SELECT COUNT(*) FROM study_description_presets WHERE organization_id = 1").fetchone()[0]
final_by_modality = conn.execute("SELECT modality, COUNT(*) FROM study_description_presets WHERE organization_id = 1 GROUP BY modality").fetchall()

conn.close()

print(f"✅ Imported: {imported} complete descriptions")
print(f"✅ Total in database: {final_count}")
print("\n📊 Final breakdown:")
for modality, count in final_by_modality:
    print(f"   {modality}: {count}")
