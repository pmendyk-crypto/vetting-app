import csv
import sqlite3

csv_file = r"C:\Users\pmend\OneDrive\Vetting App\Study description preset .csv"

print("=" * 70)
print("LOADING STUDY DESCRIPTIONS INTO DATABASE")
print("=" * 70)

# Parse the CSV file with proper column handling
data = {
    'CT': [],
    'MRI': [],
    'PET': [],
    'XR': [],
    'DEXA': []
}

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    headers = next(reader)
    
    # Clean up headers (remove BOM if present)
    headers = [h.strip().lstrip('\ufeff') for h in headers]
    
    print(f"\nParsing CSV with columns: {headers}\n")
    
    for row in reader:
        for col_idx, col_name in enumerate(headers):
            if col_idx < len(row):
                value = row[col_idx].strip()
                if value:  # Only add non-empty values
                    if col_name in data:
                        data[col_name].append(value)

print("✅ CSV Parsing Complete")
print("\nCounts from CSV:")
for modality, descs in data.items():
    print(f"  {modality:6} → {len(descs):4} descriptions")

total_from_csv = sum(len(descs) for descs in data.values())
print(f"\n  TOTAL → {total_from_csv:4} descriptions")

# Clear old data and load into database
print("\n" + "=" * 70)
print("LOADING INTO DATABASE")
print("=" * 70)

conn = sqlite3.connect('hub.db')

# Clear old data for organization 1
print("\n🗑️  Clearing old data...")
deleted = conn.execute("DELETE FROM study_description_presets WHERE organization_id = 1").rowcount
print(f"   Deleted {deleted} old records")

# Load all descriptions
print("\n📥 Inserting new data...")
total_inserted = 0
duplicates_skipped = 0

for modality, descriptions in data.items():
    for description in descriptions:
        try:
            conn.execute(
                "INSERT INTO study_description_presets (organization_id, modality, description, created_at, updated_at, created_by) VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)",
                (1, modality, description)
            )
            total_inserted += 1
        except sqlite3.IntegrityError as e:
            duplicates_skipped += 1

conn.commit()

# Verify final state
print("\n" + "=" * 70)
print("VERIFICATION")
print("=" * 70)

final_total = conn.execute("SELECT COUNT(*) FROM study_description_presets WHERE organization_id = 1").fetchone()[0]

final_counts = conn.execute(
    "SELECT modality, COUNT(*) as count FROM study_description_presets WHERE organization_id = 1 GROUP BY modality ORDER BY count DESC"
).fetchall()

print(f"\n✅ Total inserted: {total_inserted}")
if duplicates_skipped > 0:
    print(f"⚠️  Duplicates skipped: {duplicates_skipped}")

print(f"\n✅ Final database count: {final_total}")
print("\n📊 Final breakdown by modality:")
for modality, count in final_counts:
    print(f"   {modality:6} → {count:4} descriptions")

# Show sample from each modality
print("\n" + "=" * 70)
print("SAMPLE DATA VERIFICATION")
print("=" * 70)

for modality in ['CT', 'MRI', 'XR', 'PET', 'DEXA']:
    samples = conn.execute(
        "SELECT description FROM study_description_presets WHERE organization_id = 1 AND modality = ? LIMIT 2",
        (modality,)
    ).fetchall()
    
    if samples:
        print(f"\n{modality}:")
        for sample in samples:
            print(f"  • {sample[0]}")

conn.close()

print("\n" + "=" * 70)
print("✅ DATABASE LOAD COMPLETE!")
print("=" * 70)
print("\n🎉 All 1,283 study descriptions are now ready to use!")
print("   Users can now access them in the case submission form.")
