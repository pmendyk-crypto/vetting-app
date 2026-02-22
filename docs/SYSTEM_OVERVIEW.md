# Vetting App System Overview

This document summarizes the current implementation in a single place for review.

## File Summary
- app/main.py - Entrypoint, auth routes, dashboards, DB helpers, CSV export.
- app/routers/multitenant.py - Multi-tenant auth and org routes (currently not wired in main app).
- database/migrations/001_add_multi_tenant_schema.sql - Multi-tenant DB migration reference.
- templates/home.html - Admin dashboard template.
- templates/radiologist_dashboard.html - Radiologist dashboard template.
- templates/login.html and templates/index.html - Login UI templates.

## 1) User + Auth Internals (app/main.py)

### Users table schema (Postgres init)
Includes: email, password hash, name fields, and superuser flags. Org membership is tracked in memberships (not on users).

```sql
CREATE TABLE IF NOT EXISTS users (
	id SERIAL PRIMARY KEY,
	username TEXT NOT NULL UNIQUE,
	email TEXT UNIQUE,
	password_hash TEXT NOT NULL,
	salt_hex TEXT NOT NULL,
	is_superuser INTEGER NOT NULL DEFAULT 0,
	is_active INTEGER NOT NULL DEFAULT 1,
	created_at TEXT NOT NULL,
	modified_at TEXT,
	first_name TEXT,
	surname TEXT
);
```

Memberships table (org_id lives here):

```sql
CREATE TABLE IF NOT EXISTS memberships (
	id SERIAL PRIMARY KEY,
	org_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	org_role TEXT NOT NULL DEFAULT 'org_user',
	is_active INTEGER NOT NULL DEFAULT 1,
	created_at TEXT NOT NULL,
	modified_at TEXT,
	UNIQUE(org_id, user_id)
);
```

Legacy SQLite users table (includes role and radiologist_name):

```sql
CREATE TABLE IF NOT EXISTS users (
	username TEXT PRIMARY KEY,
	first_name TEXT,
	surname TEXT,
	email TEXT,
	role TEXT NOT NULL,
	radiologist_name TEXT,
	salt_hex TEXT NOT NULL,
	pw_hash_hex TEXT NOT NULL
);
```

### Password hashing + verify

```python
def hash_password(password: str, salt: bytes) -> bytes:
	return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)

def verify_user(username: str, password: str) -> dict | None:
	normalized_username = username.strip()
	if normalized_username.lower() == "superadmin":
		ensure_superadmin_user()
		normalized_password = " ".join(password.split())
		if normalized_password == "admin 111" or normalized_password == "admin111":
			...
	row = conn.execute("SELECT * FROM users WHERE username = ?", (normalized_username,)).fetchone()
	...
	salt = bytes.fromhex(row["salt_hex"])
	expected = bytes.fromhex(pw_hash_hex)
	provided = hash_password(password, salt)
	if secrets.compare_digest(provided, expected):
		return user_dict
	return None
```

### Session helpers

```python
def get_session_user(request: Request) -> dict | None:
	user = request.session.get("user")
	if not user:
		return None
	login_time = request.session.get("login_time")
	if login_time:
		current_time = time.time()
		if current_time - login_time > SESSION_TIMEOUT_MINUTES * 60:
			request.session.clear()
			return None
		request.session["login_time"] = current_time
	return user

def require_admin(request: Request) -> dict:
	user = require_login(request)
	if user.get("role") != "admin":
		raise HTTPException(status_code=403, detail="Admin only")
	return user
```

### Forgot password handlers (current state)
These do not generate a token or send email yet.

```python
@app.get("/forgot-password")
def forgot_password_page(request: Request, role: str = "admin"):
	...
	return templates.TemplateResponse("forgot_password.html", {"request": request, "role": role, "submitted": False})

@app.post("/forgot-password")
def forgot_password_submit(request: Request, role: str = Form("admin"), username: str = Form(...)):
	...
	return templates.TemplateResponse("forgot_password.html", {"request": request, "role": role, "submitted": True})
```

## 2) Case Workflow + PDF + CSV (app/main.py)

### Cases table schema (Postgres init)

```sql
CREATE TABLE IF NOT EXISTS cases (
	id TEXT PRIMARY KEY,
	created_at TEXT NOT NULL,
	patient_first_name TEXT NOT NULL,
	patient_surname TEXT NOT NULL,
	patient_referral_id TEXT,
	institution_id INTEGER,
	study_description TEXT NOT NULL,
	admin_notes TEXT,
	radiologist TEXT NOT NULL,
	uploaded_filename TEXT,
	stored_filepath TEXT,
	status TEXT NOT NULL,
	protocol TEXT,
	decision TEXT,
	decision_comment TEXT,
	vetted_at TEXT,
	org_id INTEGER
);
```

### Create new case (admin submit)

```python
@app.get("/submit")
def submit_form(request: Request):
	user = require_admin(request)
	institutions = list_institutions(org_id)
	radiologists = list_radiologists(org_id)
	return templates.TemplateResponse("submit.html", {...})

@app.post("/submit")
async def submit_case(...):
	user = require_admin(request)
	...
	conn.execute("""
		INSERT INTO cases (..., status, vetted_at, org_id)
		VALUES (?, ?, ..., "pending", None, org_id)
	""", ...)
```

### Vet/update case (radiologist action)

```python
@app.post("/vet/{case_id}")
def vet_submit(...):
	user = require_radiologist(request)
	...
	conn.execute("""
		UPDATE cases
		SET status = ?, protocol = ?, decision = ?, decision_comment = ?, vetted_at = ?
		WHERE id = ?
	""", ...)
```

### Reopen case (admin)

```python
@app.post("/admin/case/{case_id}/reopen")
def admin_reopen_case_submit(...):
	...
	conn.execute(
		"UPDATE cases SET status = ?, admin_notes = ?, decision = NULL, decision_comment = NULL, vetted_at = NULL WHERE id = ?",
		("reopened", updated_notes, case_id)
	)
```

### PDF download endpoint

```python
@app.get("/case/{case_id}/pdf")
def case_pdf(request: Request, case_id: str, inline: bool = False):
	...
	pdf_path = UPLOAD_DIR / f"{case_id}_vetting.pdf"
	c = canvas.Canvas(str(pdf_path), pagesize=A4)
	...
	return FileResponse(str(pdf_path), media_type="application/pdf")
```

### CSV export handler

```python
@app.get("/admin.csv")
def admin_dashboard_csv(...):
	...
	return StreamingResponse(iter_csv(), media_type="text/csv", headers={...})
```

## 3) Multi-tenant wiring (app/main.py + app/routers/multitenant.py)

### Tenant boundaries
- org_id exists on cases, institutions, protocols (Postgres init and migration).
- users do NOT store org_id; memberships table links user_id to org_id with org_role.
- login attaches org context using get_user_primary_membership and stores org_id in session.

Example filtering by org in admin dashboard and CSV:

```python
if org_id and not user.get("is_superuser"):
	sql += " AND c.org_id = ?"
	params.append(org_id)
```

### Router include lines (currently commented)

```python
# if MULTITENANT_ENABLED:
#     app.include_router(multitenant.router)
#     print("[INFO] Multi-tenant features enabled")
```

### multitenant.py login/select-org logic (excerpt)

```python
@router.post("/login")
def login(...):
	user = get_user_by_username(...)
	if not verify_password(...):
		return HTMLResponse("Invalid username or password", status_code=401)
	memberships = list_memberships_for_user(...)
	request.session["user_id"] = user.id
	request.session["is_superuser"] = user.is_superuser
	if len(memberships) == 1:
		request.session["current_org_id"] = memberships[0].org_id
		return RedirectResponse("/admin", status_code=302)
	return RedirectResponse("/select-org", status_code=302)

@router.get("/select-org")
def select_org(...):
	...
```

## 4) Templates (small but important)

### templates/home.html
Radiologist assignment column and PDF action:

```html
<th class="sortable" onclick="updateSort('radiologist')">Radiologist</th>
...
<td>{{ c["radiologist"] }}</td>
<td class="row-actions">
  <a href="/admin/case/{{ c['id'] }}">Open</a>
  <a href="/case/{{ c['id'] }}/pdf" target="_blank">PDF</a>
</td>
```

### templates/admin_case.html
PDF action shown as "Open vetting Form":

```html
<a href="/case/{{ case['id'] }}/pdf" target="_blank">Open vetting Form</a>
```

### templates/radiologist_dashboard.html
Action column PDF link (candidate to remove):

```html
<div class="action-links">
  <a href="/vet/{{ c.id }}">Open</a>
  <a href="/case/{{ c.id }}/pdf">PDF</a>
</div>
```

Styling blocks that control status colors and TAT warnings:

```html
.status-badge { ... }
.status-pending { background: rgba(255, 200, 0, 0.15); color: #ffc800; }
.status-reopened { background: rgba(243, 156, 18, 0.15); color: #f39c12; }
.status-vetted { background: rgba(74, 222, 128, 0.15); color: #4ade80; }
.status-rejected { background: rgba(255, 100, 100, 0.15); color: #ff6464; }
.tat-breached { color: #ff6464; }
```

### Login templates
templates/login.html (role-based view with logo text and Forgot password link):

```html
<h1 style="margin: 0;">Vetting Console</h1>
...
<a class="small" href="/forgot-password?role={{ role }}">Forgot password?</a>
```

templates/index.html (main landing login form):

```html
<form method="post" action="/login">
  ...
  <a class="small" href="/forgot-password">Forgot password?</a>
</form>
```

## 5) DB Migration Baseline (database/migrations/001_add_multi_tenant_schema.sql)

Tables created in the migration script (excerpt):

```sql
CREATE TABLE IF NOT EXISTS organisations (...);
CREATE TABLE IF NOT EXISTS users (...);
CREATE TABLE IF NOT EXISTS memberships (...);
CREATE TABLE IF NOT EXISTS radiologist_profiles (...);
CREATE TABLE IF NOT EXISTS config (...);
CREATE TABLE IF NOT EXISTS audit_logs (...);
ALTER TABLE cases ADD COLUMN org_id INTEGER DEFAULT NULL;
ALTER TABLE institutions ADD COLUMN org_id INTEGER DEFAULT NULL;
ALTER TABLE protocols ADD COLUMN org_id INTEGER DEFAULT NULL;
```
