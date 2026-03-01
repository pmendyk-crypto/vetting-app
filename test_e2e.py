import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

base_url = "http://127.0.0.1:8000"

# Create a session with retry logic
session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=1)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

print("=" * 70)
print("END-TO-END TEST: Study Descriptions Workflow")
print("=" * 70)

# Step 1: Get login page
print("\n1️⃣  Getting login page...")
try:
    response = session.get(f"{base_url}/login")
    if response.status_code == 200:
        print("   ✅ Login page loaded successfully")
    else:
        print(f"   ❌ Failed to load login page: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Step 2: Login with test admin credentials
print("\n2️⃣  Attempting to login...")
try:
    # Try common test credentials
    login_data = {
        "username": "admin",
        "password": "admin"  # This is a guess - may need to be changed
    }
    response = session.post(f"{base_url}/login_submit", data=login_data, allow_redirects=True)
    
    if "dashboard" in response.url.lower() or response.status_code == 200:
        print("   ✅ Login successful")
        print(f"   Current URL: {response.url}")
    else:
        print(f"   ⚠️  Login returned status {response.status_code}")
        print(f"   URL after login: {response.url}")
except Exception as e:
    print(f"   ❌ Error during login: {e}")

# Step 3: Try to access /submit form
print("\n3️⃣  Accessing /submit form...")
try:
    response = session.get(f"{base_url}/submit")
    if response.status_code == 200:
        print("   ✅ /submit form loaded successfully")
        # Check if the modality dropdown is in the HTML
        if 'id="modality"' in response.text or 'name="modality"' in response.text:
            print("   ✅ Modality dropdown found in HTML")
        if 'loadStudyDescriptions' in response.text:
            print("   ✅ JavaScript function found in page")
        if 'id="descriptionList"' in response.text or 'description-dropdown' in response.text:
            print("   ✅ Description dropdown container found")
    else:
        print(f"   ❌ Failed to load /submit: {response.status_code}")
        if response.status_code == 401 or response.status_code == 403:
            print("      (Not authenticated - need valid admin login)")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Step 4: Try to call the study descriptions API
print("\n4️⃣  Testing API endpoint /api/study-descriptions/by-modality/CT...")
try:
    response = session.get(f"{base_url}/api/study-descriptions/by-modality/CT")
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ API call successful")
        print(f"   CT descriptions available: {len(data)}")
        if len(data) > 0:
            print(f"   Sample: {data[0]['description']}")
        else:
            print("   ⚠️  No descriptions returned (user may not be authenticated yet)")
    else:
        print(f"   ❌ API returned status {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 70)
print("\n💡 NEXT STEPS TO TEST MANUALLY:")
print("   1. Visit http://localhost:8000/login")
print("   2. Login with your admin credentials")
print("   3. Go to http://localhost:8000/submit")
print("   4. Select a modality (CT, MRI, XR, PET, DEXA)")
print("   5. You should see a dropdown with 1-556 descriptions per modality")
print("   6. Type to search/filter the descriptions")
print("   7. Click to select one")
print("\n" + "=" * 70)
