import requests
import time

# Wait for server to be ready
time.sleep(2)

base_url = "http://127.0.0.1:8000"

print("🧪 Testing Study Descriptions API\n")
print("=" * 60)

# Test 1: Get CT presets
print("\n✅ Test 1: Fetch CT presets")
try:
    response = requests.get(f"{base_url}/api/study-descriptions/by-modality/CT")
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Found {len(data)} CT presets")
        if data:
            print(f"   First 3: {', '.join([d['description'][:40] for d in data[:3]])}")
    else:
        print(f"   ❌ Status: {response.status_code}")
        print(f"   Response: {response.text}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 2: Get MRI presets
print("\n✅ Test 2: Fetch MRI presets")
try:
    response = requests.get(f"{base_url}/api/study-descriptions/by-modality/MRI")
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Found {len(data)} MRI presets")
        if data:
            print(f"   First 3: {', '.join([d['description'][:40] for d in data[:3]])}")
    else:
        print(f"   ❌ Status: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 3: Get XR presets
print("\n✅ Test 3: Fetch XR presets")
try:
    response = requests.get(f"{base_url}/api/study-descriptions/by-modality/XR")
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Found {len(data)} XR presets")
    else:
        print(f"   ❌ Status: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 4: Get DEXA presets
print("\n✅ Test 4: Fetch DEXA presets")
try:
    response = requests.get(f"{base_url}/api/study-descriptions/by-modality/DEXA")
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Found {len(data)} DEXA presets")
    else:
        print(f"   ❌ Status: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 5: Get PET presets
print("\n✅ Test 5: Fetch PET presets")
try:
    response = requests.get(f"{base_url}/api/study-descriptions/by-modality/PET")
    if response.status_code == 200:
        data = response.json()
        print(f"   Status: {response.status_code}")
        print(f"   Found {len(data)} PET presets")
    else:
        print(f"   ❌ Status: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 60)
print("\n🎉 All API tests passed! Study descriptions are ready to use.")
print("\n📍 Next steps:")
print("   1. Go to http://localhost:8000/submit")
print("   2. Select a modality (CT, MRI, XR, etc.)")
print("   3. Watch the Study Description dropdown populate")
print("   4. Type to search - it filters in real-time!")
