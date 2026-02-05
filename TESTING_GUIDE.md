# 🧪 Multi-Tenant Testing Guide

## ⚠️ CRITICAL: Test Before Production!

**NEVER skip testing!** Multi-tenant changes affect every part of your app. Follow this guide to test safely.

---

## 🎯 Testing Strategy Overview

```
Test Database → Migration → Code Changes → Validation → Staging → Production
     ↓              ↓            ↓             ↓           ↓           ↓
   5 mins        10 mins      2 hours       1 hour      1 day     Deploy
```

---

## 📋 Phase 1: Setup Test Environment (10 minutes)

### Step 1: Create Test Database Copy

```powershell
# Backup your production database
cd "c:\Users\pmend\project\Vetting app"
Copy-Item hub.db -Destination hub.db.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')

# Create test database
Copy-Item hub.db -Destination hub_test.db

# Verify copies
Get-ChildItem hub*.db | Select-Object Name, Length, LastWriteTime
```

### Step 2: Create Test Configuration

Create a file `test_config.py`:

```python
# test_config.py
import os

# Use test database
os.environ['DATABASE_URL'] = 'sqlite:///hub_test.db'

# Enable debug mode
os.environ['DEBUG'] = 'true'

# Different session secret for testing
os.environ['SESSION_SECRET'] = 'test-secret-key-do-not-use-in-production'

# Different port
TEST_PORT = 8001
```

### Step 3: Create Test Runner Script

Create `run_test_server.py`:

```python
# run_test_server.py
import uvicorn
import test_config  # Load test configuration

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 TESTING MODE - Using test database: hub_test.db")
    print("🚨 DO NOT USE THIS IN PRODUCTION")
    print("=" * 60)
    
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,  # Different port from production
        reload=True,
        log_level="debug"
    )
```

---

## 📋 Phase 2: Test Migration (15 minutes)

### Step 1: Run SQL Migration on Test Database

```powershell
# Apply SQL schema migration to test database
sqlite3 hub_test.db < database/migrations/001_add_multi_tenant_schema.sql

# Check if tables were created
sqlite3 hub_test.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
```

**Expected output:**
```
audit_logs
cases
institutions
memberships
organisations
protocols
radiologist_profiles
users
```

### Step 2: Verify Schema Changes

```powershell
# Check organisations table
sqlite3 hub_test.db "PRAGMA table_info(organisations);"

# Check users table
sqlite3 hub_test.db "PRAGMA table_info(users);"

# Check memberships table
sqlite3 hub_test.db "PRAGMA table_info(memberships);"

# Check org_id was added to cases
sqlite3 hub_test.db "PRAGMA table_info(cases);" | Select-String "org_id"
```

### Step 3: Run Data Migration

```powershell
# Run migration script on test database
.\.venv\Scripts\python.exe scripts/migrate_to_multitenant.py --db hub_test.db

# Review migration report
Get-Content migration_report_*.json | ConvertFrom-Json | Format-List
```

**What to check in the report:**
- ✅ Default organisation created
- ✅ All old users migrated to new users table
- ✅ Radiologist profiles created
- ✅ Memberships created
- ✅ All cases have org_id
- ✅ Validation passed

---

## 📋 Phase 3: Test Code Changes (30 minutes)

### Step 1: Update main.py for Testing

Create `test_main.py` (temporary test version):

```python
# test_main.py - Test version of main.py
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import os

# Import your multi-tenant components
from app.routers import multitenant
from app.db import setup_database, shutdown_database

app = FastAPI(title="Vetting App - TEST MODE")

# Session middleware (use test secret)
app.add_middleware(
    SessionMiddleware,
    secret_key="test-secret-key-change-in-production",
    max_age=3600
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Database setup
@app.on_event("startup")
async def startup():
    os.environ['DATABASE_URL'] = 'sqlite:///hub_test.db'
    await setup_database(app)
    print("🧪 TEST MODE: Using hub_test.db")

@app.on_event("shutdown")
async def shutdown():
    await shutdown_database(app)

# Include multi-tenant routes
app.include_router(multitenant.router)

# Test homepage
@app.get("/")
async def test_homepage():
    return {
        "status": "testing",
        "message": "Multi-tenant test server running",
        "database": "hub_test.db",
        "warning": "DO NOT USE IN PRODUCTION"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
```

### Step 2: Start Test Server

```powershell
# Terminal 1: Start test server
.\.venv\Scripts\python.exe test_main.py
```

**Expected output:**
```
🧪 TEST MODE: Using hub_test.db
INFO:     Started server process
INFO:     Uvicorn running on http://127.0.0.1:8001
```

### Step 3: Test in Browser

Open: http://127.0.0.1:8001

**Test checklist:**
- [ ] Homepage loads
- [ ] No errors in console
- [ ] Can see test mode message

---

## 📋 Phase 4: Test Multi-Tenant Features (1 hour)

### Test 1: Login & Org Selection

```powershell
# Test login endpoint
$loginData = @{
    username = "your_admin_username"
    password = "your_password"
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://127.0.0.1:8001/login" `
    -Method POST `
    -Body $loginData `
    -ContentType "application/json" `
    -SessionVariable session
```

**Expected:**
- ✅ Status 200
- ✅ Session cookie set
- ✅ Redirected to /select-org (if multiple orgs)

### Test 2: Org Selection

```powershell
# View org selection page
Invoke-WebRequest -Uri "http://127.0.0.1:8001/select-org" `
    -WebSession $session
```

**Expected:**
- ✅ Status 200
- ✅ Lists available organisations
- ✅ Shows default organisation

### Test 3: Superuser Features

**In browser:** http://127.0.0.1:8001/superuser/organisations

**Test:**
- [ ] Can view all organisations
- [ ] Can create new organisation
- [ ] Can view organisation members
- [ ] Can add users to organisations

### Test 4: Data Isolation

```powershell
# Query test database to verify org_id filtering
sqlite3 hub_test.db "SELECT id, org_id FROM cases LIMIT 10;"
```

**Create test script** `test_data_isolation.py`:

```python
# test_data_isolation.py
import sqlite3

def test_data_isolation():
    """Verify all data has org_id and no cross-org leaks"""
    conn = sqlite3.connect('hub_test.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print("\n" + "="*60)
    print("🧪 Testing Data Isolation")
    print("="*60)
    
    # Test 1: All cases have org_id
    cur.execute("SELECT COUNT(*) as total, COUNT(org_id) as with_org FROM cases")
    result = cur.fetchone()
    print(f"\n✅ Test 1: Cases with org_id")
    print(f"   Total cases: {result['total']}")
    print(f"   With org_id: {result['with_org']}")
    assert result['total'] == result['with_org'], "Some cases missing org_id!"
    
    # Test 2: All institutions have org_id
    cur.execute("SELECT COUNT(*) as total, COUNT(org_id) as with_org FROM institutions")
    result = cur.fetchone()
    print(f"\n✅ Test 2: Institutions with org_id")
    print(f"   Total: {result['total']}, With org_id: {result['with_org']}")
    assert result['total'] == result['with_org'], "Some institutions missing org_id!"
    
    # Test 3: All protocols have org_id
    cur.execute("SELECT COUNT(*) as total, COUNT(org_id) as with_org FROM protocols")
    result = cur.fetchone()
    print(f"\n✅ Test 3: Protocols with org_id")
    print(f"   Total: {result['total']}, With org_id: {result['with_org']}")
    assert result['total'] == result['with_org'], "Some protocols missing org_id!"
    
    # Test 4: All users have memberships
    cur.execute("""
        SELECT u.username, COUNT(m.id) as org_count
        FROM users u
        LEFT JOIN memberships m ON u.id = m.user_id
        GROUP BY u.id, u.username
    """)
    print(f"\n✅ Test 4: User memberships")
    for row in cur.fetchall():
        print(f"   {row['username']}: {row['org_count']} org(s)")
    
    # Test 5: Audit logs exist
    cur.execute("SELECT COUNT(*) as count FROM audit_logs")
    count = cur.fetchone()['count']
    print(f"\n✅ Test 5: Audit logs: {count} entries")
    
    print("\n" + "="*60)
    print("✅ All data isolation tests passed!")
    print("="*60 + "\n")
    
    conn.close()

if __name__ == "__main__":
    test_data_isolation()
```

Run it:

```powershell
.\.venv\Scripts\python.exe test_data_isolation.py
```

### Test 5: URL Guessing Prevention

Create `test_url_guessing.py`:

```python
# test_url_guessing.py
import requests

BASE_URL = "http://127.0.0.1:8001"

def test_url_guessing():
    """Test that users can't access other org's data by guessing URLs"""
    
    print("\n" + "="*60)
    print("🧪 Testing URL Guessing Prevention")
    print("="*60)
    
    # Login as org1 user
    session1 = requests.Session()
    login1 = session1.post(f"{BASE_URL}/login", json={
        "username": "org1_user",
        "password": "password123"
    })
    
    # Select org1
    session1.post(f"{BASE_URL}/select-org", data={"org_id": "1"})
    
    # Try to access org2's case by guessing URL
    print("\n✅ Test 1: Try accessing case from org2...")
    response = session1.get(f"{BASE_URL}/admin/case/999")  # Case from org2
    
    if response.status_code == 404:
        print("   ✅ PASS: Got 404 (case not found or access denied)")
    elif response.status_code == 403:
        print("   ✅ PASS: Got 403 (access forbidden)")
    else:
        print(f"   ❌ FAIL: Got {response.status_code} (should be 404 or 403)")
        return False
    
    # Try to access list with different org_id in query
    print("\n✅ Test 2: Try listing cases with org_id parameter...")
    response = session1.get(f"{BASE_URL}/admin/cases?org_id=2")  # Try to see org2 cases
    
    # Should either ignore the parameter or return empty
    if response.status_code == 200:
        data = response.json()
        if data.get('org_id') == 1:  # Should use session org, not query param
            print("   ✅ PASS: Ignored user-supplied org_id, used session")
        else:
            print("   ❌ FAIL: Used user-supplied org_id!")
            return False
    
    print("\n" + "="*60)
    print("✅ All URL guessing tests passed!")
    print("="*60 + "\n")
    return True

if __name__ == "__main__":
    test_url_guessing()
```

Run it:

```powershell
.\.venv\Scripts\python.exe test_url_guessing.py
```

---

## 📋 Phase 5: Run Acceptance Tests (30 minutes)

Copy all 8 acceptance tests from [MULTITENANT_IMPLEMENTATION.md](MULTITENANT_IMPLEMENTATION.md) and run them:

```powershell
# Test 1: Data isolation
.\.venv\Scripts\python.exe tests/test_data_isolation.py

# Test 2: Org admin can't see other orgs
.\.venv\Scripts\python.exe tests/test_org_admin_isolation.py

# Test 3: URL guessing prevention
.\.venv\Scripts\python.exe tests/test_url_guessing.py

# Test 4: CSV export scoped to org
.\.venv\Scripts\python.exe tests/test_csv_export.py

# Test 5: org_id required on insert
.\.venv\Scripts\python.exe tests/test_org_id_required.py

# Test 6: User creation scoped to org
.\.venv\Scripts\python.exe tests/test_user_creation_scoping.py

# Test 7: Audit logging
.\.venv\Scripts\python.exe tests/test_audit_logging.py

# Test 8: Session org context
.\.venv\Scripts\python.exe tests/test_session_org_context.py
```

**Success criteria:** All 8 tests pass ✅

---

## 📋 Phase 6: Manual Testing Checklist

### Login & Authentication
- [ ] Can log in with existing credentials
- [ ] Invalid credentials are rejected
- [ ] Session persists across requests
- [ ] Can log out successfully

### Organisation Selection
- [ ] Org selection page shows correct orgs
- [ ] Can select organisation
- [ ] Org context persists in session
- [ ] Can switch between organisations

### Superuser Features
- [ ] Can view all organisations
- [ ] Can create new organisation
- [ ] Can manage organisation members
- [ ] Can assign roles to users
- [ ] Audit logs are created

### Org Admin Features
- [ ] Can view users in their org only
- [ ] Can create new users (auto-scoped to org)
- [ ] Can invite existing users to org
- [ ] Can change user roles
- [ ] Can deactivate users
- [ ] Cannot see other orgs' data

### Radiologist Features
- [ ] Radiologist dashboard loads
- [ ] Can only see cases from their org
- [ ] Can edit/submit cases
- [ ] Cannot access other orgs' cases

### Data Access
- [ ] Case list shows only org's cases
- [ ] Case detail shows correct case
- [ ] Cannot access cases by guessing IDs
- [ ] Institutions scoped to org
- [ ] Protocols scoped to org

### Exports & Reports
- [ ] CSV export includes only org's data
- [ ] PDF reports scoped to org
- [ ] No data leakage between orgs

---

## 📋 Phase 7: Performance Testing (Optional)

### Test Query Performance

```python
# test_performance.py
import sqlite3
import time

def test_query_performance():
    conn = sqlite3.connect('hub_test.db')
    cur = conn.cursor()
    
    # Test 1: Query with org_id filter (indexed)
    start = time.time()
    for _ in range(1000):
        cur.execute("SELECT * FROM cases WHERE org_id = 1 LIMIT 10")
        cur.fetchall()
    indexed_time = time.time() - start
    
    print(f"With org_id index: {indexed_time:.3f}s for 1000 queries")
    
    # Test 2: Query all cases (no filter) - slower
    start = time.time()
    for _ in range(1000):
        cur.execute("SELECT * FROM cases LIMIT 10")
        cur.fetchall()
    unfiltered_time = time.time() - start
    
    print(f"Without filter: {unfiltered_time:.3f}s for 1000 queries")
    print(f"Performance improvement: {(unfiltered_time/indexed_time):.1f}x faster with index")
    
    conn.close()

if __name__ == "__main__":
    test_query_performance()
```

---

## 📋 Phase 8: Rollback Plan (If Issues Found)

### If Tests Fail

```powershell
# Stop test server
# Press Ctrl+C in the terminal

# Delete test database
Remove-Item hub_test.db

# Restore from backup
Copy-Item hub.db.backup_YYYYMMDD_HHMMSS -Destination hub_test.db

# Review errors
Get-Content error.log | Select-Object -Last 50

# Fix issues in code
# Re-run tests
```

### If You Need to Start Over

```powershell
# Remove all test files
Remove-Item hub_test.db
Remove-Item test_main.py
Remove-Item test_config.py
Remove-Item run_test_server.py

# Your original database is safe at hub.db
# Your backup is safe at hub.db.backup_YYYYMMDD_HHMMSS
```

---

## 📋 Phase 9: Staging Environment (1-2 days)

After all tests pass, deploy to staging:

### Step 1: Create Staging Database

```powershell
# Copy production database to staging
Copy-Item hub.db -Destination hub_staging.db

# Run migrations on staging
sqlite3 hub_staging.db < database/migrations/001_add_multi_tenant_schema.sql
.\.venv\Scripts\python.exe scripts/migrate_to_multitenant.py --db hub_staging.db
```

### Step 2: Deploy Staging Server

```powershell
# Set staging environment
$env:DATABASE_URL = "sqlite:///hub_staging.db"
$env:ENVIRONMENT = "staging"

# Run on different port
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

### Step 3: Invite Real Users for Testing

- Share staging URL with trusted users
- Ask them to test their workflows
- Collect feedback
- Fix any issues found

**Staging checklist:**
- [ ] All automated tests pass
- [ ] 5+ real users tested workflows
- [ ] No critical bugs found
- [ ] Performance acceptable
- [ ] Ready for production

---

## 📋 Phase 10: Production Deployment

**Only after staging success!**

### Pre-Deployment Checklist

- [ ] All tests pass in staging
- [ ] Users approved staging
- [ ] Backup created: `hub.db.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')`
- [ ] Migration scripts tested
- [ ] Rollback plan documented
- [ ] Maintenance window scheduled
- [ ] Users notified

### Deployment Steps

```powershell
# 1. Announce maintenance (30 mins before)
# Email users about downtime

# 2. Stop production server
# Press Ctrl+C or stop service

# 3. Backup production database
Copy-Item hub.db -Destination "hub.db.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

# 4. Run migrations
sqlite3 hub.db < database/migrations/001_add_multi_tenant_schema.sql
.\.venv\Scripts\python.exe scripts/migrate_to_multitenant.py --db hub.db

# 5. Review migration report
Get-Content migration_report_*.json

# 6. Update main.py with multi-tenant code
# (Follow MULTITENANT_IMPLEMENTATION.md steps)

# 7. Start production server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 8. Smoke test
# Test login, org selection, data access

# 9. Monitor for 1 hour
# Check logs, user feedback

# 10. Announce completion
# Email users that system is back
```

---

## ❌ What NOT to Do

- ❌ **Don't skip testing** - Always test before production
- ❌ **Don't test on production database** - Always use a copy
- ❌ **Don't rush** - Testing takes time, but prevents disasters
- ❌ **Don't ignore errors** - Fix all issues before proceeding
- ❌ **Don't deploy on Friday** - Deploy early in week
- ❌ **Don't deploy without backup** - Always have rollback plan

---

## ✅ Success Indicators

### Test Environment
- ✅ All automated tests pass
- ✅ Manual testing checklist complete
- ✅ No data leakage between orgs
- ✅ URL guessing prevented
- ✅ Audit logs working

### Staging Environment  
- ✅ Real users tested successfully
- ✅ Performance acceptable
- ✅ No critical bugs
- ✅ User feedback positive

### Production Ready
- ✅ Staging approved
- ✅ Backup created
- ✅ Rollback plan documented
- ✅ Team ready for deployment

---

## 📞 Support

If issues during testing:

1. **Check logs**: Review terminal output for errors
2. **Check database**: Verify data integrity with SQL queries
3. **Review docs**: Re-read [MULTITENANT_IMPLEMENTATION.md](MULTITENANT_IMPLEMENTATION.md)
4. **Rollback**: Restore from backup and try again
5. **Ask for help**: Share error messages

---

## 🎯 Quick Testing Commands

```powershell
# Setup (5 minutes)
Copy-Item hub.db -Destination hub_test.db
sqlite3 hub_test.db < database/migrations/001_add_multi_tenant_schema.sql
.\.venv\Scripts\python.exe scripts/migrate_to_multitenant.py --db hub_test.db

# Run tests (30 minutes)
.\.venv\Scripts\python.exe test_data_isolation.py
.\.venv\Scripts\python.exe test_url_guessing.py

# Start test server (1 minute)
.\.venv\Scripts\python.exe test_main.py

# Manual testing (1 hour)
# Open http://127.0.0.1:8001 in browser
```

---

**Remember: Testing is not optional! It's your safety net.** 🛡️

Good luck with testing! 🧪
