# System Overview

This document summarizes the current live shape of the application.

## File Summary

- `app/main.py`
  - main FastAPI app, auth, owner/admin/practitioner workflows, settings, exports, PDF generation
- `app/referral_ingest.py`
  - referral parser trial support
- `templates/home.html`
  - admin dashboard and reporting UI
- `templates/radiologist_dashboard.html`
  - practitioner queue/dashboard
- `templates/owner_dashboard.html`
  - owner overview
- `templates/owner_organisation_edit.html`
  - owner organisation detail and user management
- `templates/login.html`, `templates/mfa_verify.html`
  - sign-in and MFA verification UI

## 1) User And Auth Internals

### User model and role context

Current auth/authorization data is split across:

- `users`
  - account data
  - `is_superuser`
  - MFA fields such as `mfa_required`, `mfa_enabled`, `mfa_secret`, `mfa_pending_secret`
- `memberships`
  - organisation link
  - `org_role`
  - active/inactive membership state

Organisation-aware role values in code:

- `org_admin`
- `radiology_admin`
- `radiologist`
- `org_user`

### Authentication flow

- Passwords are verified in app code using PBKDF2-HMAC SHA256.
- Sessions are managed through `SessionMiddleware`.
- Idle session timeout is `20` minutes.
- Login is two-step when MFA is enabled:
  - `POST /login`
  - `GET/POST /login/mfa`
- Required-but-not-enrolled admin-capable users are redirected to `/account` to finish MFA setup.

### Password reset

Password reset is token-based in the current code:

- `password_reset_tokens` table exists
- `GET/POST /forgot-password`
- `GET/POST /reset-password`
- SMTP-backed email sending is used when configured

## 2) Access Model

- Owner
  - `users.is_superuser = 1`
  - lands on `/owner`
- Admin
  - usually `memberships.org_role = org_admin`
  - `radiology_admin` is also accepted by `require_admin`
- Practitioner
  - `memberships.org_role = radiologist`
- Coordinator
  - `memberships.org_role = org_user`

Legacy `users.role` values are still used as fallback compatibility data.

## 3) Main Workflow Areas

### Owner workflow

- `/owner`
- `/owner/organisations`
- `/owner/organisations/{org_id}`

Owner routes support organisation creation, editing, initial admin setup, MFA requirement flags, organisation-user management, password resets, and destructive org cleanup actions.

### Admin workflow

- `/admin`
- `/admin/case/{case_id}`
- `/admin/case/{case_id}/edit`
- `/admin/case/{case_id}/reopen`
- `/admin/notify-radiologist`
- `/admin.csv`
- `/admin.events.csv`
- `/admin/dashboard-report.pdf`

The admin screen now combines worklist and dashboard reporting, rather than being just a simple case table.

### Practitioner workflow

- `/radiologist`
- `/vet/{case_id}`

Practitioners review assigned cases and submit decisions/comments. Those decisions feed the same reporting and case event model used by the admin dashboard.

### Submission and intake

- `/submit`
- `/intake/{org_id}`
- `/submit/referral-trial*`
- `/submitted/{case_id}`

## 4) Reporting And Output

Current export/report surfaces:

- case CSV: `/admin.csv`
- case event CSV: `/admin.events.csv`
- dashboard PDF: `/admin/dashboard-report.pdf`
- case PDF: `/case/{case_id}/pdf`
- case timeline PDF/CSV:
  - `/admin/case/{case_id}/timeline.pdf`
  - `/admin/case/{case_id}/timeline.csv`

Organisation-specific report header/footer text is configured through `/settings/report`.

## 5) Settings And Master Data

`/settings` currently manages:

- institutions
- practitioner profiles
- protocols
- organisation users
- report header/footer text
- study description presets

Supporting API routes also exist for study-description and protocol selection helpers.

## 6) Route Scope Note

`app/routers/multitenant.py` still exists in the repo, but it is not the mounted route path that users follow today. Current live behaviour is driven by `app/main.py`, owner routes, and membership-aware permission helpers.
