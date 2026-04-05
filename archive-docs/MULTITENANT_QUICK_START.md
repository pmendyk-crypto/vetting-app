# Multi-Tenant Implementation: Quick Start Reference

## 📁 Files Created

### 1. Database & Migrations
- **`database/migrations/001_add_multi_tenant_schema.sql`** - Full schema migration
- **`scripts/migrate_to_multitenant.py`** - Automated data migration script

### 2. Backend Code
- **`app/models.py`** - Data models and CRUD operations for all multi-tenant entities
- **`app/dependencies.py`** - FastAPI dependencies for auth, org context, and role checking
- **`app/routers/multitenant.py`** - Example route handlers with org scoping

### 3. Frontend Templates
- **`templates/superuser_organisations.html`** - Superuser: Manage organisations
- **`templates/superuser_org_members.html`** - Superuser: Manage org members
- **`templates/admin_users.html`** - Org admin: Manage users in their org

### 4. Documentation
- **`MULTITENANT_IMPLEMENTATION.md`** - Full implementation guide
- **`MULTITENANT_QUICK_START.md`** - This file

---

## ⚡ 5-Minute Quick Start

### Step 1: Backup
```bash
cp hub.db hub.db.backup
```

### Step 2: Create schema
```bash
sqlite3 hub.db < database/migrations/001_add_multi_tenant_schema.sql
```

### Step 3: Migrate data
```bash
python scripts/migrate_to_multitenant.py
```

### Step 4: Update main.py
```python
# Add imports
from app.models import create_user, get_user, get_organisation, ...
from app.dependencies import require_login, require_org_context, require_org_admin, ...
from app.routers.multitenant import router as mt_router

# Register router
app.include_router(mt_router)

# Update login endpoint to handle multi-org
@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    # ... existing auth logic ...
    memberships = list_memberships_for_user(db_conn, user.id, active_only=True)
    if len(memberships) == 1:
        request.session["current_org_id"] = memberships[0].org_id
    else:
        return RedirectResponse("/select-org", status_code=302)
```

### Step 5: Update existing routes
All existing routes must:
1. Add `org_user: tuple = Depends(require_org_context)`
2. Extract `current_user, org_id = org_user`
3. Filter by `org_id` in all queries
4. Set `org_id` on inserts

**Before:**
```python
@app.get("/admin/cases")
async def list_cases(request: Request):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cases")
    return {"cases": cursor.fetchall()}
```

**After:**
```python
@app.get("/admin/cases")
async def list_cases(
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    cursor = db_conn.cursor()
    # ADD THIS LINE:
    cursor.execute("SELECT * FROM cases WHERE org_id = ?", (org_id,))
    return {"cases": cursor.fetchall()}
```

### Step 6: Test
```python
from tests.test_multitenant import test_data_isolation
test_data_isolation()
```

---

## 🔑 Key Concepts

### User Identity
- **Users** are global accounts with `username`, `password_hash`
- **Superusers** have `is_superuser=true` flag
- **Role per org** defined in `memberships` table

### Organisation Context
- Stored in **session**: `request.session["current_org_id"]`
- All protected routes require it
- Superusers can switch orgs

### Data Isolation
- Every tenant table has `org_id` column
- **All queries must filter by org_id**
- **All inserts must set org_id from session**
- Direct ID access must validate `org_id` match

### Roles
```python
class OrgRole:
    SUPERUSER = "superuser"     # Platform admin
    ORG_ADMIN = "org_admin"     # Admin in org
    RADIOLOGIST = "radiologist" # Radiologist
    ORG_USER = "org_user"       # Regular user
```

---

## 🛠️ Common Code Patterns

### Pattern 1: Get Current Org Context
```python
@app.get("/dashboard")
async def dashboard(
    request: Request,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    # current_user = {"user_id": int, "username": str, "is_superuser": bool}
    # org_id = current organisation
```

### Pattern 2: Query with Org Filter
```python
cursor = db_conn.cursor()
cursor.execute(
    "SELECT * FROM cases WHERE org_id = ? AND status = ?",
    (org_id, "pending")
)
results = cursor.fetchall()
```

### Pattern 3: Insert with Org Context
```python
cursor = db_conn.cursor()
cursor.execute("""
    INSERT INTO cases (id, org_id, patient_name, ...)
    VALUES (?, ?, ?, ...)
""", (case_id, org_id, "John", ...))  # org_id from session
db_conn.commit()
```

### Pattern 4: Prevent URL Guessing
```python
@app.get("/case/{case_id}")
async def get_case(
    case_id: str,
    org_user: tuple = Depends(require_org_context),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_user
    
    # Query with org_id filter
    cursor = db_conn.cursor()
    cursor.execute(
        "SELECT * FROM cases WHERE id = ? AND org_id = ?",
        (case_id, org_id)
    )
    case = cursor.fetchone()
    
    if not case:
        raise HTTPException(404)  # 404 if wrong org
```

### Pattern 5: Require Org Admin
```python
@app.post("/admin/settings/users/create")
async def create_user(
    request: Request,
    org_admin: tuple = Depends(require_org_admin),  # Replaces require_org_context
    db_conn: sqlite3.Connection = Depends(get_db)
):
    current_user, org_id = org_admin
    # User MUST be org_admin in this org
```

### Pattern 6: Require Superuser
```python
@app.get("/superuser/organisations")
async def list_all_orgs(
    request: Request,
    superuser: dict = Depends(require_superuser),
    db_conn: sqlite3.Connection = Depends(get_db)
):
    # User MUST be superuser
    orgs = list_organisations(db_conn)
    return {"organisations": orgs}
```

### Pattern 7: Audit Log
```python
from app.models import create_audit_log, AuditAction

create_audit_log(
    db_conn,
    org_id=org_id,
    user_id=current_user["user_id"],
    action=AuditAction.USER_CREATED,
    target_user_id=new_user_id,
    details=json.dumps({"username": "john", "email": "john@test.com"})
)
db_conn.commit()
```

### Pattern 8: Check Membership Role
```python
from app.models import get_membership_by_org_user, OrgRole

membership = get_membership_by_org_user(db_conn, org_id, user_id)

if membership and membership.org_role == OrgRole.RADIOLOGIST:
    # User is radiologist in this org
    pass
```

---

## 📋 Checklist: Routes to Update

For each existing route in your app:

- [ ] Add `org_user: tuple = Depends(require_org_context)` parameter
- [ ] Extract `current_user, org_id = org_user`
- [ ] Add `WHERE org_id = ?` to all SELECT queries
- [ ] Add `org_id = ?` parameter to all INSERT queries
- [ ] Validate `org_id` on direct object access (by ID)
- [ ] Return 404 (not 403) when org_id doesn't match
- [ ] Update radiologist queries to use `assigned_radiologist_user_id`
- [ ] Add audit log for sensitive operations

### Routes that need updating:

**List views:**
- [ ] `/admin` (cases list)
- [ ] `/radiologist` (queue)
- [ ] `/admin/settings` (settings)

**Detail/Edit views:**
- [ ] `/admin/case/{id}`
- [ ] `/admin/case/{id}/edit`
- [ ] `/vet/{case_id}`
- [ ] `/case/{id}/attachment`

**Create/Submit:**
- [ ] `/submit`
- [ ] `/submitted/{id}`
- All POST endpoints in settings

**Export:**
- [ ] `/admin.csv`
- [ ] `/case/{id}/pdf`

---

## 🔒 Security Review

### For Each Route: Ask Yourself

1. **Does it filter by org_id?**
   - ✅ If YES: data is scoped
   - ❌ If NO: **security bug**

2. **Does it validate org_id on direct access?**
   - ✅ If YES: URL guessing prevented
   - ❌ If NO: **security bug**

3. **Does it set org_id from session (not request)?**
   - ✅ If YES: org_id cannot be forged
   - ❌ If NO: **security bug**

4. **Does it return 404 for wrong org?**
   - ✅ If YES: no info leakage
   - ❌ If NO: **info leak**

5. **Is there an audit log for admin actions?**
   - ✅ If YES: audit trail exists
   - ⚠️ If NO: not critical but recommended

---

## 🐛 Troubleshooting

### Issue: "No organisation context set"
**Cause:** Route requires org context but session missing
**Fix:** Ensure login flow sets `current_org_id` in session

### Issue: "User has no organisation access"
**Cause:** User not a member of the org
**Fix:** Create membership record: `create_membership(db, org_id, user_id)`

### Issue: Cases from other orgs visible
**Cause:** Query missing `WHERE org_id = ?` filter
**Fix:** Add org_id filter to SELECT query

### Issue: Cannot create user in org
**Cause:** Org admin trying to add user from different org
**Fix:** Check membership exists in current org only

### Issue: Radiologist cannot see assigned cases
**Cause:** Cases using old `radiologist` (text) field instead of `assigned_radiologist_user_id`
**Fix:** Update case records: `UPDATE cases SET assigned_radiologist_user_id = ? WHERE radiologist = ?`

---

## 📈 Performance Tips

### Add these indexes after migration:
```sql
CREATE INDEX idx_cases_org_id ON cases(org_id);
CREATE INDEX idx_cases_org_status ON cases(org_id, status);
CREATE INDEX idx_institutions_org_id ON institutions(org_id);
CREATE INDEX idx_protocols_org_id ON protocols(org_id);
CREATE INDEX idx_memberships_org_user ON memberships(org_id, user_id);
```

### Query patterns for performance:
```python
# Good: single query with org_id
cursor.execute(
    "SELECT * FROM cases WHERE org_id = ? AND status = ?",
    (org_id, "pending")
)

# Bad: query all then filter in Python
cursor.execute("SELECT * FROM cases")
results = [c for c in cursor.fetchall() if c["org_id"] == org_id]
```

---

## 📞 Support

For issues or questions:

1. Check `MULTITENANT_IMPLEMENTATION.md` for detailed info
2. Review route examples in `app/routers/multitenant.py`
3. Check acceptance tests for patterns
4. Review model functions in `app/models.py`

---

## ✅ Success Criteria

Your multi-tenant implementation is complete when:

- ✅ Two organisations exist with different users
- ✅ User in org A cannot see org B's cases
- ✅ Org admin cannot manage users in other orgs
- ✅ CSV export only includes own org's data
- ✅ Direct URL access validates org_id (returns 404)
- ✅ No records exist without org_id
- ✅ Superuser can view all orgs
- ✅ All admin actions are logged
- ✅ Session-based org context works
- ✅ No security issues in penetration testing
