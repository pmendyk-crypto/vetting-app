# Multi-Tenant Implementation Guide & Acceptance Tests

## 📋 Overview

This guide covers implementing true multi-tenant data isolation in your FastAPI + Jinja2 app. The implementation provides:

- **Strict data isolation** between organisations
- **Role-based access control** (superuser, org_admin, radiologist, org_user)
- **Secure session-based org context**
- **Audit logging** of all admin actions
- **Complete backward compatibility** migration path

---

## 🚀 Implementation Steps

### Step 1: Backup Database
```bash
cp hub.db hub.db.backup
```

### Step 2: Run Schema Migration
```bash
python database/migrations/001_add_multi_tenant_schema.sql
# OR for SQLite command line:
sqlite3 hub.db < database/migrations/001_add_multi_tenant_schema.sql
```

### Step 3: Run Data Migration
```bash
python scripts/migrate_to_multitenant.py
```

This script will:
- Create a default organisation
- Migrate all existing users
- Migrate all radiologist records
- Populate org_id on all tenant records
- Create audit logs
- Validate data integrity

### Step 4: Update app/main.py

Import the new models and dependencies:
```python
from app.models import (
    create_user, get_user, get_organisation, list_organisations,
    get_membership_by_org_user, list_memberships_for_user,
    create_membership, update_membership, create_audit_log
)
from app.dependencies import (
    require_login, require_org_context, require_superuser, require_org_admin,
    verify_user_in_org, enforce_org_id
)
```

Register the multi-tenant router:
```python
from app.routers.multitenant import router as mt_router
app.include_router(mt_router)
```

### Step 5: Update Existing Routes

**Critical: All existing routes must be updated to:**
1. Use `require_org_context` dependency
2. Filter queries by org_id
3. Validate record ownership before returning

Example - before:
```python
@app.get("/admin/cases")
async def list_cases(request: Request):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cases ORDER BY created_at DESC")
    cases = cursor.fetchall()
    return render_template("admin_case.html", cases=cases)
```

Example - after:
```python
@app.get("/admin/cases", response_class=HTMLResponse)
async def list_cases(
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    cursor = db_conn.cursor()
    # CRITICAL: Filter by org_id
    cursor.execute(
        "SELECT * FROM cases WHERE org_id = ? ORDER BY created_at DESC",
        (org_id,)
    )
    cases = cursor.fetchall()
    return templates.TemplateResponse("admin_case.html", {
        "request": request,
        "cases": cases,
        "org_id": org_id
    })
```

### Step 6: Update Route for Case Access

**Before:**
```python
@app.get("/admin/case/{case_id}")
async def get_case(case_id: str, request: Request):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    if not case:
        raise HTTPException(404)
    return render_template("case_detail.html", case=case)
```

**After (with org validation):**
```python
@app.get("/admin/case/{case_id}", response_class=HTMLResponse)
async def get_case(
    case_id: str,
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    
    # Query with org_id filter to prevent URL guessing
    cursor = db_conn.cursor()
    cursor.execute(
        "SELECT * FROM cases WHERE id = ? AND org_id = ?",
        (case_id, org_id)
    )
    case = cursor.fetchone()
    
    if not case:
        raise HTTPException(404, detail="Case not found")
    
    # Belt-and-suspenders validation
    enforce_org_id(db_conn, org_id, case["org_id"])
    
    return templates.TemplateResponse("case_detail.html", {
        "request": request,
        "case": case
    })
```

### Step 7: Update POST Endpoints

When creating tenant-scoped records, always set org_id from session:

**Before:**
```python
@app.post("/submit")
async def submit_case(
    request: Request,
    first_name: str = Form(...),
    # ... other fields
    db_conn: sqlite3.Connection = Depends(get_db)
):
    cursor = db_conn.cursor()
    cursor.execute("""
        INSERT INTO cases (id, created_at, patient_first_name, ...)
        VALUES (?, ?, ?, ...)
    """, (case_id, now, first_name, ...))
    db_conn.commit()
```

**After (org-scoped):**
```python
@app.post("/submit")
async def submit_case(
    request: Request,
    first_name: str = Form(...),
    # ... other fields
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    
    cursor = db_conn.cursor()
    cursor.execute("""
        INSERT INTO cases (id, created_at, patient_first_name, org_id, ...)
        VALUES (?, ?, ?, ?, ...)
    """, (case_id, now, first_name, org_id, ...))  # org_id set from session
    db_conn.commit()
```

### Step 8: Update Radiologist Routes

Radiologists are now identified by their user record + optional profile:

**Before:**
```python
@app.get("/radiologist")
async def radiologist_queue(request: Request):
    radiologist_name = request.session.get("radiologist_name")
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cases WHERE radiologist = ?", (radiologist_name,))
    # ...
```

**After:**
```python
@app.get("/radiologist", response_class=HTMLResponse)
async def radiologist_queue(
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    
    # User must have radiologist role
    membership = get_membership_by_org_user(db_conn, org_id, current_user["user_id"])
    if not membership or membership.org_role != OrgRole.RADIOLOGIST:
        raise HTTPException(403, detail="Radiologist access required")
    
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT * FROM cases 
        WHERE org_id = ? AND assigned_radiologist_user_id = ?
        ORDER BY created_at
    """, (org_id, current_user["user_id"]))
    # ...
```

### Step 9: Update CSV Export

Ensure exports respect org boundaries:

**Before:**
```python
@app.get("/admin.csv")
async def export_csv(request: Request):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cases")
    # ... generate CSV from all cases
```

**After:**
```python
@app.get("/admin.csv")
async def export_csv(
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    
    cursor = db_conn.cursor()
    # CRITICAL: Only export org's data
    cursor.execute(
        "SELECT * FROM cases WHERE org_id = ? ORDER BY created_at DESC",
        (org_id,)
    )
    # ... generate CSV
```

---

## 🛡️ Security Checklist

- [ ] All tenant-scoped tables have org_id column
- [ ] All GET queries filter by org_id + user auth
- [ ] All POST/PUT queries set org_id from session
- [ ] All DELETE operations validate org_id
- [ ] Direct record access (by ID) validates org_id
- [ ] CSV exports filter by org_id
- [ ] PDF exports filter by org_id
- [ ] API endpoints use `require_org_context` or `require_superuser`
- [ ] Radiologist identification uses user_id instead of name
- [ ] Old users table is archived (not deleted)
- [ ] Audit logs created for all admin actions
- [ ] Session timeout implemented
- [ ] Password reset flow requires org context

---

## 📊 Database Schema Summary

### Core Tables

**organisations**
```
id (PK), name, slug (unique), is_active, created_at, modified_at
```

**users**
```
id (PK), username (unique), email, password_hash, salt_hex, 
is_superuser, is_active, created_at, modified_at
```

**memberships**
```
id (PK), org_id (FK), user_id (FK), org_role, is_active, created_at, modified_at
UNIQUE(org_id, user_id)
```

**radiologist_profiles**
```
id (PK), user_id (unique FK), gmc, specialty, display_name, created_at, modified_at
```

**audit_logs**
```
id (PK), org_id (FK), user_id (FK), action, target_user_id, target_org_id, 
details (JSON), created_at
```

### Tenant-Scoped Tables (Updated)

**cases**
```
... existing columns ...
org_id (FK to organisations)  ← ADDED
```

**institutions**
```
... existing columns ...
org_id (FK to organisations)  ← ADDED
```

**protocols**
```
... existing columns ...
org_id (FK to organisations)  ← ADDED
```

---

## 🧪 Acceptance Tests

### Test 1: Data Isolation Between Orgs

```python
def test_two_orgs_data_isolation():
    """Case created in Org A invisible to Org B."""
    
    # Setup: Create two orgs
    org_a_id = create_organisation(db, "Org A", "org-a")
    org_b_id = create_organisation(db, "Org B", "org-b")
    
    # Create users
    user_a_id = create_user(db, "user_a", "pass_hash", "salt")
    user_b_id = create_user(db, "user_b", "pass_hash", "salt")
    
    # Assign users to different orgs
    create_membership(db, org_a_id, user_a_id, OrgRole.ORG_USER)
    create_membership(db, org_b_id, user_b_id, OrgRole.ORG_USER)
    
    # Create case in Org A
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO cases (id, org_id, patient_first_name, ...)
        VALUES (?, ?, ?, ...)
    """, ("case-1", org_a_id, "John", ...))
    db.commit()
    
    # User B tries to access case (should fail)
    client = TestClient(app)
    
    # Login as user_b, set org context to org_b
    response = client.get("/admin/case/case-1", 
                         session={"user_id": user_b_id, "current_org_id": org_b_id})
    
    assert response.status_code == 404  # Case not found in user_b's org
```

### Test 2: Org Admin Cannot Access Other Org's Users

```python
def test_org_admin_isolation():
    """Org A admin cannot manage Org B's users."""
    
    # Setup
    org_a_id = create_organisation(db, "Org A", "org-a")
    org_b_id = create_organisation(db, "Org B", "org-b")
    
    admin_a = create_user(db, "admin_a", "hash", "salt")
    admin_b = create_user(db, "admin_b", "hash", "salt")
    user_b = create_user(db, "user_b", "hash", "salt")
    
    create_membership(db, org_a_id, admin_a, OrgRole.ORG_ADMIN)
    create_membership(db, org_b_id, admin_b, OrgRole.ORG_ADMIN)
    create_membership(db, org_b_id, user_b, OrgRole.ORG_USER)
    
    # Admin A tries to deactivate user_b (should fail)
    cursor = db.cursor()
    
    # Admin A is in org_a, trying to access org_b's membership
    cursor.execute("""
        SELECT * FROM memberships 
        WHERE org_id = ? AND user_id = ?
    """, (org_a_id, user_b))  # Querying wrong org
    
    result = cursor.fetchone()
    assert result is None  # No membership found (good!)
```

### Test 3: URL Guessing Prevention

```python
def test_url_guessing_prevention():
    """Cannot access case by guessing URL from different org."""
    
    org_a_id = create_organisation(db, "Org A", "org-a")
    org_b_id = create_organisation(db, "Org B", "org-b")
    
    user_b_id = create_user(db, "user_b", "hash", "salt")
    create_membership(db, org_b_id, user_b_id, OrgRole.ORG_USER)
    
    # Create case in org_a
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO cases (id, org_id, ...)
        VALUES ('case-secret', ?, ...)
    """, (org_a_id,))
    db.commit()
    
    # User B tries to access via URL
    client = TestClient(app)
    response = client.get("/admin/case/case-secret",
                         session={"user_id": user_b_id, "current_org_id": org_b_id})
    
    assert response.status_code == 404  # Case not found
    assert "case-secret" not in response.text  # No info leakage
```

### Test 4: Superuser Can Switch Orgs

```python
def test_superuser_org_switching():
    """Superuser can view any org."""
    
    org_a_id = create_organisation(db, "Org A", "org-a")
    org_b_id = create_organisation(db, "Org B", "org-b")
    
    superuser_id = create_user(db, "superuser", "hash", "salt", is_superuser=True)
    
    # Superuser creates cases in both orgs
    cursor = db.cursor()
    cursor.execute("INSERT INTO cases (id, org_id, ...) VALUES (?, ?, ...)", 
                   ("case-a", org_a_id, ...))
    cursor.execute("INSERT INTO cases (id, org_id, ...) VALUES (?, ?, ...)", 
                   ("case-b", org_b_id, ...))
    db.commit()
    
    # Superuser switches to org_a
    response = client.post("/select-org", data={"org_id": org_a_id},
                          session={"user_id": superuser_id, "is_superuser": True})
    
    assert response.status_code == 302  # Redirect to admin
    
    # Can see org_a case
    response = client.get("/admin/case/case-a",
                         session={"user_id": superuser_id, "current_org_id": org_a_id})
    assert response.status_code == 200
    
    # Switch to org_b
    response = client.post("/select-org", data={"org_id": org_b_id},
                          session={"user_id": superuser_id, "is_superuser": True})
    
    # Can now see org_b case
    response = client.get("/admin/case/case-b",
                         session={"user_id": superuser_id, "current_org_id": org_b_id})
    assert response.status_code == 200
```

### Test 5: CSV Export Respects Org Boundaries

```python
def test_csv_export_org_scoped():
    """CSV export only includes org's cases."""
    
    org_a_id = create_organisation(db, "Org A", "org-a")
    org_b_id = create_organisation(db, "Org B", "org-b")
    
    user_a = create_user(db, "user_a", "hash", "salt")
    create_membership(db, org_a_id, user_a, OrgRole.ORG_USER)
    
    # Create 3 cases in org_a, 2 in org_b
    cursor = db.cursor()
    for i in range(3):
        cursor.execute("INSERT INTO cases (id, org_id, ...) VALUES (?, ?, ...)",
                      (f"case-a-{i}", org_a_id, ...))
    for i in range(2):
        cursor.execute("INSERT INTO cases (id, org_id, ...) VALUES (?, ?, ...)",
                      (f"case-b-{i}", org_b_id, ...))
    db.commit()
    
    # User A exports CSV
    response = client.get("/admin.csv",
                         session={"user_id": user_a, "current_org_id": org_a_id})
    
    assert response.status_code == 200
    csv_content = response.content.decode()
    
    # Should have 3 org_a cases
    assert csv_content.count("case-a") == 3
    
    # Should NOT have org_b cases
    assert "case-b" not in csv_content
```

### Test 6: Creating Record Without Org_id Impossible

```python
def test_org_id_required_on_insert():
    """Cannot insert tenant record without org_id."""
    
    cursor = db.cursor()
    
    # Try to insert case without org_id (simulating direct DB access)
    # This should fail due to NOT NULL constraint or app validation
    
    # App-level validation (in route)
    client = TestClient(app)
    
    # Without session org context
    response = client.post("/submit",
                          data={"first_name": "John", ...},
                          session={})  # No current_org_id
    
    # Should fail - no org context
    assert response.status_code in [400, 401]
```

### Test 7: Org Admin Creates User Only in Own Org

```python
def test_org_admin_creates_user_in_own_org():
    """Org admin creating user → user gets membership in that org only."""
    
    org_a_id = create_organisation(db, "Org A", "org-a")
    org_b_id = create_organisation(db, "Org B", "org-b")
    
    admin_a = create_user(db, "admin_a", "hash", "salt")
    create_membership(db, org_a_id, admin_a, OrgRole.ORG_ADMIN)
    
    # Admin A creates new user
    client = TestClient(app)
    response = client.post("/admin/settings/users/create",
                          data={"username": "new_user", "email": "new@test.com",
                               "password": "pass", "org_role": "org_user"},
                          session={"user_id": admin_a, "current_org_id": org_a_id})
    
    # New user should be created and member of org_a ONLY
    new_user = get_user_by_username(db, "new_user")
    assert new_user is not None
    
    # Check memberships
    memberships = list_memberships_for_user(db, new_user.id)
    assert len(memberships) == 1
    assert memberships[0].org_id == org_a_id
    assert memberships[0].org_role == "org_user"
```

### Test 8: Audit Logging Works

```python
def test_audit_logging():
    """Admin actions are logged."""
    
    org_id = create_organisation(db, "Test Org", "test-org")
    admin = create_user(db, "admin", "hash", "salt")
    create_membership(db, org_id, admin, OrgRole.ORG_ADMIN)
    
    # Create new user
    client = TestClient(app)
    response = client.post("/admin/settings/users/create",
                          data={"username": "user1", "email": "u@test.com",
                               "password": "pass", "org_role": "org_user"},
                          session={"user_id": admin, "current_org_id": org_id})
    
    # Check audit log
    logs = list_audit_logs(db, org_id, limit=10)
    
    assert len(logs) > 0
    assert logs[0].action == "user_created"
    assert logs[0].org_id == org_id
    assert logs[0].user_id == admin
```

---

## 🔍 Validation Queries

Run these to verify data integrity after migration:

```sql
-- 1. All cases have org_id
SELECT COUNT(*) as cases_without_org FROM cases WHERE org_id IS NULL;
-- Expected: 0

-- 2. All institutions have org_id
SELECT COUNT(*) as insts_without_org FROM institutions WHERE org_id IS NULL;
-- Expected: 0

-- 3. All users migrated
SELECT COUNT(*) as new_users FROM users_new;
SELECT COUNT(*) as old_users FROM users;
-- Expected: same counts

-- 4. All users have at least one membership
SELECT COUNT(DISTINCT u.id) as users_no_membership
FROM users_new u
WHERE u.id NOT IN (SELECT user_id FROM memberships);
-- Expected: 0

-- 5. All memberships belong to existing users and orgs
SELECT COUNT(*) as orphaned_memberships
FROM memberships m
WHERE m.user_id NOT IN (SELECT id FROM users_new)
   OR m.org_id NOT IN (SELECT id FROM organisations);
-- Expected: 0

-- 6. Audit logs exist
SELECT COUNT(*) as audit_count FROM audit_logs;
-- Expected: > 0
```

---

## ⚠️ Breaking Changes

1. **Users table schema** - Old users table renamed internally, new schema used
2. **Radiologist field** - "radiologist" (text name) → "assigned_radiologist_user_id" (FK)
3. **Role field** - "role" on user → "org_role" on membership
4. **Session context** - Requires "current_org_id" in session for protected routes
5. **API routes** - All routes must use org context dependency

---

## 🚨 Common Mistakes to Avoid

1. ❌ Forgetting org_id filter on SELECT
2. ❌ Not setting org_id from session on INSERT
3. ❌ Returning 500 instead of 404 for missing org_id (info leak)
4. ❌ Querying without org_id filter in loops
5. ❌ Not validating org_id on direct object access
6. ❌ Forgetting to update radiologist assignment logic
7. ❌ Not creating audit logs for sensitive operations
8. ❌ Allowing users to set org_id themselves (always from session)

---

## 📚 References

- See `app/models.py` for CRUD functions
- See `app/dependencies.py` for auth helpers
- See `app/routers/multitenant.py` for route examples
- See `scripts/migrate_to_multitenant.py` for migration details
- See `database/migrations/001_add_multi_tenant_schema.sql` for schema
