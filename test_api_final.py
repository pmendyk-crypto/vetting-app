import requests
import time

# Wait for server if needed
time.sleep(1)

base_url = "http://127.0.0.1:8000"

print("=" * 70)
print("TESTING STUDY DESCRIPTIONS API")
print("=" * 70)

modalities = ['CT', 'MRI', 'XR', 'PET', 'DEXA']

for modality in modalities:
    try:
        response = requests.get(f"{base_url}/api/study-descriptions/by-modality/{modality}")
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ {modality:6} → {len(data):3} descriptions available")
            if data and len(data) > 0:
                # Show first 2 examples
                for item in data[:2]:
                    desc = item.get('description', '')[:50]
                    print(f"           • {desc}...")
        else:
            print(f"\n❌ {modality:6} → Error: {response.status_code}")
    except Exception as e:
        print(f"\n❌ {modality:6} → Connection error: {e}")

print("\n" + "=" * 70)
print("✅ API TEST COMPLETE")
print("=" * 70)
print("\n📍 Next step: Open http://localhost:8000/submit in your browser")
print("   Select a modality and watch the dropdown populate with your data!")
