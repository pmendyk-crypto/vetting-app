FILE: V3_CHANGE_REQUEST_FOR_VSCODE_AI.md
PROJECT: Vetting App
SCOPE: Live bug fixes + future enhancements (V3)

STACK ASSUMPTION (based on provided overview)
- FastAPI in app/main.py
- Jinja templates in /templates
- SessionMiddleware with session dict
- Cases table stores current state
- Multi-tenant schema exists (Postgres) with memberships, radiologist_profiles, audit_logs
- Legacy SQLite users table still referenced in verify_user and role checks

IMPORTANT CONSTRAINTS
1) Enforce permissions server-side (not just remove UI links).
2) Tenant isolation: non-superuser must only access their org_id.
3) Preserve current "cases" current-state fields, but add event history table for audit.
4) Implement changes primarily in app/main.py and templates, plus add one new SQL migration.

============================================================
A) LIVE BUGS
============================================================

A1) Forgot password: implement email reset link with token
CURRENT
- /forgot-password exists but only shows "submitted": True and no token/email.

TARGET
- Flow: request email -> send reset link -> set new password -> invalidate token

FILES TO CHANGE
- app/main.py
- templates/forgot_password.html (if exists) and possibly templates/login.html, templates/index.html
- Add migration: database/migrations/002_password_reset_and_case_events.sql
- Optional: create a tiny helper module app/emailer.py (only if main.py is getting too large)

DATABASE
Add table (Postgres and SQLite compatible)
CREATE TABLE password_reset_tokens (
  id SERIAL/INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  token_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL,
  requested_ip TEXT,
  requested_ua TEXT
);
Index: (user_id), (token_hash)

IMPLEMENTATION IN app/main.py
1) Add env config:
   - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
   - APP_BASE_URL (example: https://yourdomain.com)
2) Add helper functions:
   - generate_token() -> plain token
   - hash_token(token) -> sha256 hex string (or hmac with APP_SECRET)
   - send_email(to, subject, body)
   - get_user_by_email(email) for Postgres users table
3) Replace /forgot-password POST:
   - Accept email (not username)
   - Always return same confirmation message
   - If email exists and user is_active:
       a) create token, store token_hash, expiry (now + 60 minutes), created_at, ip/ua
       b) email reset link: {APP_BASE_URL}/reset-password?token=PLAIN_TOKEN
4) Add routes:
   - GET /reset-password?token=...
       validate token_hash exists, not expired, not used
       show template reset_password.html with hidden token
   - POST /reset-password
       validate again, set new password_hash, update modified_at
       mark token used_at
       redirect /login with success message

PASSWORD STORAGE NORMALISATION (must fix mismatch)
You currently have two schemes:
- Postgres users table has password_hash + salt_hex (schema)
- Legacy SQLite uses pw_hash_hex + salt_hex

ACTION
- For Postgres path, implement verify_password_postgres(email/username, password):
   expected = bytes.fromhex(password_hash or pw_hash_hex) depending on actual column name
   provided = pbkdf2_hmac sha256 with salt_hex
- Decide one canonical column name in Postgres. Your schema says password_hash.
  Ensure password_hash stores hex string of pbkdf2 output.
- When setting new password, always update Postgres users.password_hash and users.salt_hex.

A1 ACCEPTANCE
- Forgot password request sends email (or logs email in dev) and does not reveal whether email exists.
- Reset link works once, expires after 60 minutes, cannot be reused.
- Password update allows login.

A2) Remove logo from main login page
CURRENT
- templates/index.html and templates/login.html show "Vetting Console" text. You requested removing logo from main login page.
ACTION
- Remove logo/branding block from templates/index.html only (main landing).
- Keep role-based login.html unchanged unless you explicitly want both removed.

A2 ACCEPTANCE
- index.html renders without the logo/header block, layout remains clean.

============================================================
B) FUTURE DEVELOPMENT
============================================================

B1) Org dashboard improvements (templates/home.html + app/main.py)

B1a) Radiologist column: dropdown to assign/change
CURRENT
- home.html shows {{ c["radiologist"] }} as text.

TARGET
- Dropdown populated by list_radiologists(org_id)
- On change, POST to endpoint that updates cases.radiologist
- Record audit event with old/new and user performing change

FILES
- templates/home.html
- app/main.py

SERVER-SIDE
1) Create endpoint:
   POST /admin/case/{case_id}/assign-radiologist
   Body: radiologist (string)
   Checks:
     - require_admin (or org admin once roles clarified)
     - validate case belongs to org_id for non-superuser
     - validate radiologist exists for org_id (from radiologist_profiles or your list source)
   DB:
     - UPDATE cases SET radiologist=? WHERE id=?
     - Insert into case_events (see B3) event_type="ASSIGNED" with comment "old -> new"
2) UI:
   - Replace td with a <select> and a small "Save" button, or auto-submit onchange.

NOTE ABOUT ROLES
Your require_admin checks user.role == "admin" but Postgres users table does not include role.
You are currently mixing legacy SQLite role logic.
ACTION REQUIRED
- Use memberships.org_role for org role checks in Postgres.
- For now, treat "admin dashboard" access as:
   - is_superuser OR membership.org_role IN ('org_admin','radiology_admin')
If you have not created these roles yet, keep require_admin but refactor it to consult memberships for Postgres users.

B1b) Action column: change "PDF amend" to "Download"
CURRENT
- home.html has link text "PDF"
TARGET
- Rename link text to "Download"
- Keep href the same (/case/{id}/pdf)

FILES
- templates/home.html
- templates/admin_case.html (where it says "Open vetting Form")

ACCEPTANCE
- Admin dashboard shows "Download" not "PDF" or "PDF amend"
- Admin case page uses consistent wording

B2) Radiologist dashboard restrictions + styling
B2a) Remove PDF link for radiologists and block server-side
CURRENT
- templates/radiologist_dashboard.html includes /case/{id}/pdf link.
TARGET
- Remove link in radiologist dashboard
- Enforce server-side restrictions in app/main.py for /case/{case_id}/pdf:
   Radiologist role must be blocked from downloading.

FILES
- templates/radiologist_dashboard.html
- app/main.py

IMPLEMENTATION
1) In /case/{case_id}/pdf:
   - user = require_login(request)
   - Determine user permissions:
       if user is radiologist: return 403
   - Also enforce org_id match for non-superuser
2) Keep allow for admins and superusers.

ACCEPTANCE
- Radiologist dashboard shows only "Open" for case
- Radiologists cannot access /case/{id}/pdf even via direct URL

B2b) Page colours alignment
You provided CSS blocks for status badges.
ACTION
- Standardise container background and padding to match admin dashboard.
- Ensure no inline styles conflict.
- Minimal change: add consistent body background and card background.
FILES
- templates/radiologist_dashboard.html (and shared base if any)

ACCEPTANCE
- No mismatched background blocks, consistent spacing.

B3) Vetting process history: step-by-step record
CURRENT
- cases table stores current status/protocol/decision/comment/vetted_at
- reopen wipes decision and vetted_at

TARGET
- Add event history table: case_events
- Every state change writes an immutable event row
- Show timeline in case page

FILES
- database/migrations/002_password_reset_and_case_events.sql
- app/main.py
- templates/admin_case.html (and radiologist case view if separate)

DB TABLE
CREATE TABLE case_events (
  id SERIAL/INTEGER PRIMARY KEY,
  case_id TEXT NOT NULL,
  org_id INTEGER,
  event_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  user_id INTEGER,
  username TEXT,
  org_role TEXT,
  decision TEXT,
  protocol TEXT,
  comment TEXT
);
Indexes: (case_id), (org_id), (created_at)

EVENTS TO WRITE
1) On case submission:
   event_type = "SUBMITTED"
   comment can include admin_notes summary if desired
2) On vet:
   event_type = "VETTED"
   include decision, protocol, decision_comment
3) On reopen:
   event_type = "REOPENED"
   comment = reopen reason/comment
4) Optional:
   event_type = "ASSIGNED" for radiologist assignment changes (B1a)

IMPLEMENTATION IN app/main.py
- Add helper: insert_case_event(case_id, org_id, event_type, user, decision=None, protocol=None, comment=None)
- Ensure created_at is UTC ISO string
- Determine user_id and username:
   - For Postgres users, use users.id and users.username
   - For legacy SQLite-only sessions, store username in session and user_id can be NULL
- Update endpoints:
   a) POST /submit: after INSERT into cases, insert_case_event SUBMITTED
   b) POST /vet/{case_id}: after UPDATE cases, insert_case_event VETTED
   c) POST /admin/case/{case_id}/reopen: after UPDATE cases, insert_case_event REOPENED

UI TIMELINE
- In templates/admin_case.html:
   - Query case events ordered by created_at asc
   - Render list: timestamp, event_type, username, decision/protocol/comment
- For radiologist case view, same timeline is useful, read-only.

ACCEPTANCE
- Every submit/vet/reopen results in a new case_events row with timestamp.
- Timeline shows full history including multiple re-vets.

B4) CSV export: auditable summary + optional detailed export
CURRENT
- /admin.csv outputs current case fields only.

TARGET
- Improve /admin.csv columns:
   - case_id
   - org_id or organisation name if available
   - submitted_at (from SUBMITTED event)
   - reopened (Y/N)
   - reopened_at (latest REOPENED)
   - reopened_by (latest REOPENED username)
   - latest_decision
   - latest_decision_at
   - latest_vetted_by
   - latest_protocol
   - latest_protocol_at
   - current_status
   - radiologist (assigned)
   - patient_referral_id
   - study_description
- Add /admin.events.csv optional:
   - one row per event with all event fields for audit

FILES
- app/main.py
- templates/home.html (optional link to detailed export)

IMPLEMENTATION
- Update admin_dashboard_csv() to join/lookup events.
  Simplest approach:
   1) Query cases (with org filter)
   2) For each case, query events for that case (or query all events for case_ids in one pass and group in Python)
- Prefer one-pass for performance:
   SELECT * FROM case_events WHERE case_id IN (...) ORDER BY created_at
  Group by case_id in Python.

ACCEPTANCE
- CSV includes reopened indicators and timestamps and usernames.
- Optional detailed events CSV can fully reconstruct audit trail.

B5) Vetting form layout and required final decision fields
CURRENT
- PDF generated in /case/{id}/pdf using reportlab, likely missing org name and radiologist GMC.

TARGET
- PDF must include:
  - Organisation name
  - Final decision block: vetted by (radiologist full name), position, GMC number
- Vetting UI should display org name at top.

DATA SOURCE
You have radiologist_profiles in migration baseline.
ACTION
- Use radiologist_profiles to store:
   full_name, position, gmc_number, user_id, org_id
- When generating PDF:
   - Look up org name from organisations by case.org_id
   - Look up radiologist profile by matching:
       - assigned radiologist username OR user_id if available
       - within same org_id

FILES
- app/main.py (PDF generation in case_pdf)
- templates/admin_case.html (show org name)
- templates/radiologist case view (if exists)

ACCEPTANCE
- PDF includes organisation name and vetted-by details with GMC.
- If profile missing, show "GMC: MISSING" and block final vet if you choose strict mode.

B6) External submission page for organisations (self-service)
TARGET
- Simple external page that creates a new case into an org dashboard without radiology admin manually re-typing.
- Must not allow cross-org leakage.

RECOMMENDED MVP APPROACH
- Create per-organisation "intake token" stored in config table:
   key="intake_token:{org_id}" value="<random>"
- External form URL:
   /intake/{org_id}?token=...
- Validate token matches config before accepting submission.
- Rate limit per IP.

FILES
- app/main.py
- templates/intake_submit.html (new)
- database migration: add config key if not present (you already have config table)

ENDPOINTS
- GET /intake/{org_id}
- POST /intake/{org_id}
On submit:
- Insert into cases with org_id and status="pending" and radiologist empty or "unassigned"
- Insert case_events SUBMITTED with username="external" or NULL user_id

ACCEPTANCE
- Org can submit case using link.
- Case appears in admin dashboard under that org.
- No access to other orgs without valid token.

B7) Multi-tenant management dashboard: make KPI cards live and add tabs
CURRENT
- home.html shows 4 stats: Organisation, Total Users, Total cases, Superuser

TARGET
- Make clickable navigation to:
   Organisations tab
   Users tab
   Cases tab (optional)
- Remove Superusers card if redundant.

FILES
- templates/home.html
- app/main.py (routes)
- templates/admin_orgs.html (new)
- templates/admin_users.html (new)

ROUTES
- GET /super/orgs
- GET /super/users
- GET /super/cases (optional)
Permissions:
- superuser only

ACCEPTANCE
- Cards link to correct pages and show filtered data.

B8) Multi-tenant billing CSV export (superuser)
TARGET
- Export per org counts within date range
- Use SUBMITTED event timestamps for counting submitted cases
- Optionally count VETTED events for completed

FILES
- app/main.py
- templates/admin_billing.html (new)

ROUTE
- GET /super/billing.csv?from=YYYY-MM-DD&to=YYYY-MM-DD
Output columns:
- org_id
- org_name
- submitted_count
- vetted_count
- period_from
- period_to

ACCEPTANCE
- Superuser can export billing data across orgs.

============================================================
C) SECURITY AND PERMISSION FIXES (REQUIRED)
============================================================

C1) Fix role checks to support memberships (Postgres)
CURRENT
- require_admin checks user.get("role") == "admin"
- Postgres users does not have role, org_role is in memberships

ACTION
- Introduce helper in app/main.py:
  get_current_org_context(request) -> (user_id, is_superuser, current_org_id, org_role)
- Update require_admin to:
  - allow is_superuser
  - else require org_role in ('org_admin','radiology_admin')
- Update require_radiologist similarly: org_role == 'radiologist'

C2) Protect /case/{case_id}/pdf and all case endpoints with org filter
- Validate case.org_id == current_org_id for non-superuser.
- Radiologist cannot download PDF.

C3) Timestamps
- Use UTC ISO 8601 consistently.

============================================================
D) MIGRATIONS
============================================================

Create new migration file:
database/migrations/002_password_reset_and_case_events.sql

Include:
1) password_reset_tokens table
2) case_events table
3) any missing indexes
4) optional config key support (if config table exists already, no schema change needed)

If you support both Postgres and SQLite:
- Use compatible SQL where possible, otherwise create two migration variants:
  002_postgres.sql and 002_sqlite.sql

============================================================
E) MINIMAL TEMPLATE EDITS SUMMARY
============================================================
- templates/index.html: remove logo/header block
- templates/home.html:
  - radiologist dropdown + assign endpoint call
  - rename PDF link text to Download
- templates/admin_case.html:
  - rename link text to Download or Open PDF consistently
  - show org name
  - add timeline render
- templates/radiologist_dashboard.html:
  - remove PDF link
  - adjust styling consistency
- Add templates/reset_password.html
- Add templates/intake_submit.html
- Optional: add superuser pages templates

============================================================
F) DONE-DEFINITION CHECKLIST
============================================================
1) Password reset:
   - request by email
   - token stored hashed, expires, single-use
   - email sent (or logged in dev)
2) Radiologist cannot download PDF (UI and server enforced)
3) case_events created for submit/vet/reopen (and assignment if implemented)
4) Timeline visible in case view
5) CSV includes reopen and decision audit fields + optional detailed events export
6) PDF includes org name and vetted-by (name, position, GMC)
7) External intake page creates cases into correct org
8) Superuser dashboard navigation and billing export implemented
````</attachment>``and I think none of the ASCII provided in the 2 files is disallowed. Need to update? The user requests to include in the document; we already created separate file. But they might want this in SYSTEM_OVERVIEW? They asked with whole change request; probably want new file with that content. We already created. Need inform location. Provide response. Maybe add note in SYSTEM_OVERVIEW referencing? But they said no links. They might want appended to overview. But they said 