import csv

csv_file = r"C:\Users\pmend\OneDrive\Vetting App\Study description preset .csv"

# Parse the CSV properly with correct headers
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    headers = next(reader)  # Get the header row
    
print("=" * 70)
print("CSV STRUCTURE ANALYSIS")
print("=" * 70)
print(f"\nHeaders found: {headers}")
print(f"Number of columns: {len(headers)}\n")

# Initialize data structure
data = {col: [] for col in headers}

# Count non-empty values per column
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    next(reader)  # Skip header
    
    row_count = 0
    for row in reader:
        row_count += 1
        for col_idx, col_name in enumerate(headers):
            if col_idx < len(row) and row[col_idx].strip():
                data[col_name].append(row[col_idx].strip())

print("=" * 70)
print("STUDY DESCRIPTIONS COUNT PER MODALITY")
print("=" * 70)

total = 0
for modality, descriptions in data.items():
    count = len(descriptions)
    total += count
    if count > 0:
        print(f"\n✅ {modality:6} : {count:4} descriptions")
        # Show first 3 examples
        print(f"         Examples:")
        for desc in descriptions[:3]:
            print(f"           • {desc}")
        if count > 3:
            print(f"           ... and {count - 3} more")

print("\n" + "=" * 70)
print(f"TOTAL STUDY DESCRIPTIONS: {total}")
print("=" * 70)

# Show a summary
print("\nSummary by modality:")
for modality, descriptions in sorted(data.items(), key=lambda x: len(x[1]), reverse=True):
    if len(descriptions) > 0:
        print(f"  {modality:6} → {len(descriptions):4} items")

print("\n✅ Ready to load into database!")
