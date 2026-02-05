# Multi-Tenant Architecture: Visual Reference

## 🏗️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         WEB BROWSER / CLIENT                         │
└────────────┬────────────────────────────────────────────────────────┘
             │
             │ HTTP/HTTPS
             │
┌────────────▼────────────────────────────────────────────────────────┐
│                          FASTAPI APP                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Auth Routes     │  │  Admin Routes    │  │  Case Routes     │  │
│  │  ├─ /login       │  │  ├─ /admin       │  │  ├─ /cases       │  │
│  │  ├─ /logout      │  │  ├─ /settings    │  │  ├─ /case/{id}   │  │
│  │  └─ /select-org  │  │  └─ /manage-*    │  │  └─ /vet/{id}    │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
│           │                     │                     │             │
│  ┌────────▼─────────────────────▼─────────────────────▼───────────┐ │
│  │           DEPENDENCY INJECTION LAYER                           │ │
│  │  ┌────────────────────────────────────────────────────────┐  │ │
│  │  │  require_login()                                       │  │ │
│  │  │  require_org_context()  ←─ Org scoping goes here     │  │ │
│  │  │  require_org_admin()                                  │  │ │
│  │  │  require_superuser()                                  │  │ │
│  │  └────────────────────────────────────────────────────────┘  │ │
│  │           │                                                    │ │
│  │  ┌────────▼──────────────────────────────────────────────┐   │ │
│  │  │  SESSION VALIDATION                                  │   │ │
│  │  │  ├─ Check user_id exists in session                 │   │ │
│  │  │  ├─ Verify current_org_id set                       │   │ │
│  │  │  ├─ Validate user is member of org                  │   │ │
│  │  │  └─ Return (current_user, org_id)                   │   │ │
│  │  └────────┬───────────────────────────────────────────┘   │ │
│  └───────────┼──────────────────────────────────────────────────┘ │
│              │                                                    │
│  ┌───────────▼──────────────────────────────────────────────┐   │
│  │         MODELS & CRUD LAYER (app/models.py)             │   │
│  │  ┌────────────────────────────────────────────────────┐  │   │
│  │  │  Organisation()  User()  Membership()              │  │   │
│  │  │  create_user()   list_organisations()              │  │   │
│  │  │  create_membership()  get_membership_by_org_user()│  │   │
│  │  └────────────────┬───────────────────────────────────┘  │   │
│  └──────────────────┼──────────────────────────────────────────┘  │
└─────────────────────┼───────────────────────────────────────────────┘
                      │
                      │ SQL with org_id filters
                      │
        ┌─────────────▼──────────────────┐
        │      DATABASE LAYER            │
        │                                │
        │  ┌──────────────────────────┐  │
        │  │ SQLITE or POSTGRESQL     │  │
        │  │                          │  │
        │  │ ┌──────────────────────┐ │  │
        │  │ │ organisations        │ │  │
        │  │ │ users                │ │  │
        │  │ │ memberships          │ │  │
        │  │ │ radiologist_profiles │ │  │
        │  │ │ audit_logs           │ │  │
        │  │ │                      │ │  │
        │  │ │ cases (org_id)       │ │  │
        │  │ │ institutions (org_id)│ │  │
        │  │ │ protocols (org_id)   │ │  │
        │  │ └──────────────────────┘ │  │
        │  └──────────────────────────┘  │
        └────────────────────────────────┘
```

---

## 📊 Data Flow: User Login & Org Selection

```
START: User visits /login
  │
  ├─→ POST /login
  │   ├─ Verify username/password
  │   ├─ Query: SELECT * FROM users WHERE username = ?
  │   └─ IF auth fails → return 401
  │
  ├─→ IF auth success:
  │   ├─ Query memberships: SELECT * FROM memberships WHERE user_id = ?
  │   │
  │   ├─ IF single_membership:
  │   │  └─ Set session: current_org_id = membership.org_id
  │   │  └─ Redirect to /admin ✓
  │   │
  │   ├─ IF multiple_memberships:
  │   │  └─ Redirect to /select-org (show list of orgs)
  │   │
  │   └─ IF superuser:
  │      └─ Redirect to /select-org (show all orgs)
  │
  └─→ END: User now has (user_id, current_org_id, is_superuser) in session
```

---

## 🔐 Data Isolation: Case Access Flow

```
REQUEST: GET /admin/case/case-123
  │
  ├─→ DEPENDENCY: require_org_context
  │   ├─ Check session["user_id"] exists → 401 if not
  │   ├─ Check session["current_org_id"] exists → 400 if not
  │   ├─ IF not superuser:
  │   │  └─ Query: SELECT * FROM memberships WHERE org_id = ? AND user_id = ?
  │   │  └─ IF not found → 403 forbidden
  │   └─ Return (current_user, org_id)
  │
  ├─→ ROUTE HANDLER: get_case(case_id, org_user, db_conn)
  │   ├─ current_user, org_id = org_user
  │   │
  │   ├─ Query with org_id filter:
  │   │  └─ SELECT * FROM cases 
  │   │     WHERE id = 'case-123' AND org_id = ? 
  │   │     (org_id from session)
  │   │
  │   ├─ IF NOT found:
  │   │  └─ Return 404 ✓ (prevents info leak)
  │   │
  │   └─ IF found:
  │      ├─ enforce_org_id() → validates record.org_id == session org_id
  │      └─ Return case data ✓
  │
  └─→ END: Case returned or 404
```

---

## 🗂️ Database Schema: Multi-Tenant Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ORGANISATIONS                                 │
├─────────────────────────────────────────────────────────────────────┤
│ id (PK) │ name           │ slug          │ is_active │ created_at  │
├─────────┼────────────────┼───────────────┼───────────┼─────────────┤
│ 1       │ Hospital ABC   │ hospital-abc  │ 1         │ 2024-01-01  │
│ 2       │ Clinic XYZ     │ clinic-xyz    │ 1         │ 2024-01-02  │
└─────────┴────────────────┴───────────────┴───────────┴─────────────┘
     △
     │
     │ 1:N relationship
     │
┌─────────────────────────────────────────────────────────────────────┐
│                        USERS (Global)                                │
├─────────────────────────────────────────────────────────────────────┤
│ id (PK) │ username │ email         │ is_superuser │ is_active      │
├─────────┼──────────┼───────────────┼──────────────┼────────────────┤
│ 1       │ john     │ john@test.com │ 0            │ 1              │
│ 2       │ admin    │ admin@test.com│ 1            │ 1              │
└─────────┴──────────┴───────────────┴──────────────┴────────────────┘
     △
     │ M:N relationship (through memberships)
     │
┌──────────────────────────────────────────────────────────────────────┐
│                       MEMBERSHIPS                                     │
├──────────────────────────────────────────────────────────────────────┤
│ id │ org_id │ user_id │ org_role      │ is_active │ created_at      │
├────┼────────┼─────────┼───────────────┼───────────┼─────────────────┤
│ 1  │ 1      │ 1       │ org_admin     │ 1         │ 2024-01-01      │
│ 2  │ 1      │ 2       │ radiologist   │ 1         │ 2024-01-02      │
│ 3  │ 2      │ 1       │ org_user      │ 1         │ 2024-01-03      │
└────┴────────┴─────────┴───────────────┴───────────┴─────────────────┘
     △
     │ N:1 relationship
     │
     ├─ org_id → organisations.id
     └─ user_id → users.id

KEY INSIGHTS:
- User 1 has org_admin role in org 1
- User 1 has org_user role in org 2 (different org, different role!)
- User 2 has radiologist role in org 1 only
```

---

## 🔒 Access Control Decision Tree

```
                          USER MAKES REQUEST
                                 │
                    ┌────────────┴────────────┐
                    │                         │
              PUBLIC ROUTE?             PROTECTED ROUTE?
                    │                         │
                   YES                       NO
                    │                         │
              Allow access              Check Authentication
              (no login needed)              │
                                    ┌────────┴────────┐
                                    │                 │
                            User in session?    No user
                                    │                 │
                                   YES              Return 401
                                    │
                            require_org_context
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                  current_org_id?         No org context
                        │                       │
                       YES                   Return 400
                        │
                    Superuser?
                    ┌───┴───┐
                   YES      NO
                    │        │
                  Allow   Check Membership
                    │        │
                    │    ┌───┴────┐
                    │    │         │
                    │  Active    Inactive
                    │   member     member
                    │    │         │
                    │   Allow   Return 403
                    │    │
                 ┌──┴────┴──┐
                 │           │
          Org scoped   Admin route?
          query filter      │
             for all   ┌────┴────┐
          data access YES        NO
                       │         │
                    Check    Check
                    role     membership
                       │      │
                ┌──────┴──┐   │
                │         │   │
            Allowed   Forbidden Allow
                                 │
                                 │ Query with
                                 │ org_id filter
                                 │
                                 Return data
                                 (org-scoped)
```

---

## 📝 Query Evolution: Before vs After

### SELECT Query

**BEFORE (single-tenant):**
```sql
SELECT * FROM cases 
ORDER BY created_at DESC;
```
❌ Returns cases from ALL organisations!

**AFTER (multi-tenant):**
```sql
SELECT * FROM cases 
WHERE org_id = ? 
ORDER BY created_at DESC;
-- Parameter: org_id from session
```
✅ Returns cases only from current organisation

---

### INSERT Query

**BEFORE (single-tenant):**
```python
cursor.execute("""
    INSERT INTO cases (id, created_at, patient_name, ...)
    VALUES (?, ?, ?, ...)
""", (case_id, now, "John", ...))
```
❌ org_id is NULL or unset!

**AFTER (multi-tenant):**
```python
cursor.execute("""
    INSERT INTO cases (id, org_id, created_at, patient_name, ...)
    VALUES (?, ?, ?, ?, ...)
""", (case_id, org_id, now, "John", ...))
# org_id comes from session, never from user input
```
✅ Every record tagged with org_id

---

### DELETE Query

**BEFORE (single-tenant):**
```python
cursor.execute("DELETE FROM cases WHERE id = ?", (case_id,))
```
❌ Could delete case from wrong org!

**AFTER (multi-tenant):**
```python
cursor.execute(
    "DELETE FROM cases WHERE id = ? AND org_id = ?",
    (case_id, org_id)
)
if cursor.rowcount == 0:
    raise HTTPException(404)  # Not found in this org
```
✅ Can only delete case from current org

---

## 🎭 Role-Based Access Control Matrix

```
                    Public  Login   Org User  Radiologist  Org Admin  Superuser
                    ─────   ─────   ────────  ───────────  ────────   ─────────
Landing page        ✅      ✅       ✅        ✅           ✅         ✅
Login page          ✅      ✅       ✅        ✅           ✅         ✅
My profile          ❌      ✅       ✅        ✅           ✅         ✅
View org cases      ❌      ✅       ✅        ✅           ✅         ✅
View radiologist queue
                    ❌      ✅       ❌        ✅           ❌         ✅
Vet/approve case    ❌      ✅       ❌        ✅           ❌         ✅
Manage org users    ❌      ✅       ❌        ❌           ✅         ✅
Manage org settings ❌      ✅       ❌        ❌           ✅         ✅
View all orgs       ❌      ✅       ❌        ❌           ❌         ✅
Create organisation ❌      ✅       ❌        ❌           ❌         ✅
Manage all users    ❌      ✅       ❌        ❌           ❌         ✅

KEY:
✅ = Access allowed
❌ = Access denied (403 or redirect to login)
* All org-scoped data filtered by current org
```

---

## 🔄 Session Data Lifecycle

```
LOGIN                          USER SESSION                    LOGOUT
  │                                  │                            │
  ├─ Validate credentials           │                            │
  │                                  │                            │
  ├─ Set session:                   │                            │
  │  - user_id = 123                │                            │
  │  - username = "john"            │                            │
  │  - is_superuser = false         │                            │
  │                                  │                            │
  ├─→ Select Org                     │                            │
  │    Set session:                  │                            │
  │  - current_org_id = 5           │ ← ALL REQUESTS USE THIS     │
  │                                  │    TO SCOPE DATA           │
  │                                  │                            │
  │                                  ├─ Every route dependency:   │
  │                                  │  require_org_context()     │
  │                                  │  ├─ Read current_org_id    │
  │                                  │  ├─ Validate membership    │
  │                                  │  └─ Pass to route handler  │
  │                                  │                            │
  │                                  ├─ Every route handler:      │
  │                                  │  - Filter by org_id        │
  │                                  │  - Set org_id on inserts   │
  │                                  │  - Validate org_id         │
  │                                  │                            │
  │                                  ├─ Switch Org (superuser):   │
  │                                  │  Set current_org_id = 9    │
  │                                  │  (next request scopes to 9)│
  │                                  │                            │
  │                                  ├─ Logout:                   │
  │                                  └─→ Clear session
                                         - Delete user_id
                                         - Delete current_org_id
                                         - Redirect to login
```

---

## 📈 Scaling Path: Single → Multi-Tenant

```
MONTH 1: Single-tenant vetting app
┌─────────────────────┐
│   Organisation      │
│   (just one)        │
├─────────────────────┤
│ Users (global)      │
│ Cases               │
│ Radiologists        │
└─────────────────────┘

MONTH 2-3: Multi-tenant implementation
┌──────────────────────┬──────────────────────┬──────────────────────┐
│  Organisation 1      │  Organisation 2      │  Organisation 3      │
│  (Hospital ABC)      │  (Clinic XYZ)        │  (Imaging Center)    │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ Cases (org_id=1)     │ Cases (org_id=2)     │ Cases (org_id=3)     │
│ Users (member)       │ Users (member)       │ Users (member)       │
│ Institutions         │ Institutions         │ Institutions         │
└──────────────────────┴──────────────────────┴──────────────────────┘
        △                      △                      △
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                    Shared Users table
                    (Global authentication)
                    Shared Memberships table
                    (Org assignment + roles)

MONTH 6+: SaaS Platform
┌─────────────────────────────────────────────────────────────────┐
│                    SaaS VETTING PLATFORM                         │
├──────────────┬──────────────┬──────────────┬──────────────────┤
│     Org 1    │     Org 2    │     Org 3    │      Org N       │
│   Hospital   │    Clinic    │   Imaging    │   ...New Orgs    │
│             │              │              │   Added via API  │
└──────────────┴──────────────┴──────────────┴──────────────────┘
        │            │             │              │
        └────────────┴─────────────┴──────────────┘
                     │
          Org Admin Dashboard
          Superuser Control Panel
          Billing & Subscriptions
          API Access
          Usage Analytics
          Org-level Feature Flags
```

---

## 🚨 Security: Attack Prevention

```
ATTACK: URL GUESSING for case 123

Attacker (Org B user) tries: GET /admin/case/case-123
                                (but case-123 is in Org A)

DEFENSE LAYERS:
                  
Layer 1: Session validation
  ├─ Check user_id in session ✅
  └─ Check current_org_id in session ✅

Layer 2: Membership validation
  └─ SELECT * FROM memberships 
     WHERE org_id = ? AND user_id = ?
     └─ NOT FOUND → 403 ❌

Layer 3: Data scoping
  └─ SELECT * FROM cases
     WHERE id = 'case-123' AND org_id = ?
     (org_id from session, not from attacker)
     └─ NOT FOUND in Org B → 404 ✅

RESULT: ✅ SECURE - Attacker cannot see case

If any layer failed:
  ❌ Layer 1 missing → User can fake org_id → Data leak!
  ❌ Layer 2 missing → User gets access → Data leak!
  ❌ Layer 3 missing → Query returns wrong org data → Data leak!
```

---

## 📊 Performance Impact

```
Query: SELECT * FROM cases WHERE org_id = ? AND status = ?

WITHOUT INDEX:
  Execution: Full table scan (10,000 cases)
  Time: ~200ms
  Load: High I/O

WITH INDEX on org_id:
  Execution: Index lookup
  Time: ~5ms  ← 40x faster!
  Load: Low I/O

RECOMMENDATION:
  CREATE INDEX idx_cases_org_id ON cases(org_id);
  CREATE INDEX idx_cases_org_status ON cases(org_id, status);

COST:
  Storage: +2% per table
  Insert time: +1% (index update)
  Query time: -90% (index lookup)
```

---

This visual reference helps understand the multi-tenant architecture at a glance! 🎯
