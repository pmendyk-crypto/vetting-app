# RadFlow Architecture

## Overview

RadFlow is a FastAPI application with server-rendered Jinja templates for referral intake, admin triage, practitioner vetting, and owner-level organisation management. It runs against SQLite by default for local work and can use PostgreSQL in deployed environments via `DATABASE_URL`.

The current implementation is centred in `app/main.py`. The app includes:

- public landing and sign-in
- session-based authentication with optional TOTP MFA
- organisation-scoped admin and practitioner workspaces
- owner/superuser organisation management
- PDF and CSV reporting/export

## Core Stack

| Layer | Current implementation |
|---|---|
| Backend | FastAPI |
| Templates | Jinja2 |
| Auth/session | Starlette `SessionMiddleware` + password hashing in app code |
| MFA | Authenticator-app TOTP with QR provisioning |
| Database | SQLite locally, PostgreSQL-compatible code paths in production |
| Reporting | ReportLab PDF generation + CSV exports |
| File storage | Local uploads by default, optional Azure Blob storage |

## Runtime Structure

| Area | Main routes/templates | Purpose |
|---|---|---|
| Public/auth | `/`, `/login`, `/login/mfa`, `/forgot-password`, `/reset-password`, `/logout` | Entry, password reset, MFA step-up, sign-out |
| Account | `/account`, `/account/edit`, `/account/change-password`, `/account/mfa/*` | Profile maintenance and self-service MFA enrollment |
| Admin workspace | `/admin`, `/admin/case/{id}`, `/admin/case/{id}/edit`, `/admin/case/{id}/reopen`, `/admin.csv`, `/admin.events.csv`, `/admin/dashboard-report.pdf`, `/admin/notify-radiologist` | Operational dashboard, case management, exports, practitioner notifications |
| Practitioner workspace | `/radiologist`, `/vet/{case_id}` | Assigned queue and vetting decisions |
| Submission | `/submit`, `/submitted/{case_id}`, `/intake/{org_id}` | New case creation and org-specific intake |
| Settings | `/settings` and `/settings/*` | Institutions, protocols, users, report text, radiologist/profile metadata |
| Owner workspace | `/owner`, `/owner/organisations`, `/owner/organisations/{org_id}` and child user/org routes | Superuser-only organisation administration |

## Current Roles And Permission Model

There are two layers of permission data in the current code:

1. `users.is_superuser`
   Used for the owner-level account with cross-organisation access.
2. `memberships.org_role`
   Used for organisation-scoped access in normal operation.

Current organisation role names in code:

| Stored value | UI label | Effective access |
|---|---|---|
| `org_admin` | Admin | Full organisation admin access |
| `radiology_admin` | Admin | Accepted by `require_admin`; treated as admin-capable |
| `radiologist` | Practitioner | Practitioner queue and vetting access |
| `org_user` | Coordinator | Non-admin organisation user |

Legacy `users.role` values (`admin`, `radiologist`, `user`) still exist and are mapped into the membership model for compatibility and setup flows.

### Permission boundaries

- `require_superuser` gates owner routes.
- `require_admin` allows:
  - any `is_superuser` user
  - organisation members with `org_role` of `org_admin` or `radiology_admin`
  - legacy fallback users with `role == "admin"`
- `require_radiologist` allows:
  - any `is_superuser` user
  - organisation members with `org_role == "radiologist"`
  - legacy fallback users with `role == "radiologist"`

## Authentication And MFA Flow

Current sign-in is a two-step session flow:

1. User posts credentials to `POST /login`.
2. Login attempts are rate-limited by client IP.
3. Credentials are checked against the current user store.
4. If the account has `mfa_enabled` and `mfa_secret`, the session is parked in a pending MFA state and the user is redirected to `GET /login/mfa`.
5. `POST /login/mfa` verifies a 6-digit TOTP code and only then completes the login session.
6. On success, the app stores a session with user identity, role context, MFA flags, and a session id.
7. Post-login redirect is role-sensitive:
   - superuser -> `/owner`
   - admin -> `/admin`
   - practitioner -> `/radiologist`
   - users with required-but-not-enabled MFA -> `/account?msg=mfa_required`

### MFA enrollment and enforcement

- User records include `mfa_required`, `mfa_enabled`, `mfa_secret`, and `mfa_pending_secret`.
- Users enroll from `/account`:
  - `POST /account/mfa/begin` generates a pending secret
  - the account page renders the TOTP secret and QR code
  - `POST /account/mfa/enable` verifies the first code and promotes the secret to active MFA
  - `POST /account/mfa/disable` disables MFA when allowed
- Admin access is MFA-aware:
  - if an admin-capable account is marked `mfa_required` but has not completed enrollment, `require_admin` returns `403` with `MFA enrollment required`
  - the global auth handler redirects signed-in users in that state to `/account?msg=mfa_required`
- Owner and organisation user creation/edit flows can mark admin or user accounts as MFA-required.

## Main Operational Flows

### Submission

- Cases are created through `/submit` or org-specific `/intake/{org_id}`.
- Submission stores patient/referral details, assignment, notes, and uploaded referral files.
- Status starts as pending and the confirmation page is `/submitted/{case_id}`.

### Admin workflow

- `/admin` is the main workspace for organisation admins and superusers.
- The admin page combines:
  - worklist filtering and sorting
  - dashboard metrics and charts
  - case assignment/reassignment
  - reopen flow
  - CSV export
  - PDF dashboard report export
- `/admin/case/{id}` and `/admin/case/{id}/edit` handle case review and editing.
- `/admin/notify-radiologist` sends practitioner notifications and records notify events when configured.

### Practitioner workflow

- `/radiologist` shows the logged-in practitioner's queue.
- `/vet/{case_id}` is the decision screen.
- Decisions and timeline data flow back into the shared admin reporting surface.

### Owner workflow

- `/owner` is reserved for `is_superuser` accounts.
- Owners can create organisations, seed the first admin, require MFA for that admin, manage organisation users, reset passwords, and delete organisations or child records from the owner organisation screens.

## Reporting And Dashboard Changes

The current admin dashboard is more than a simple case list. It now includes:

- KPI-style summary cards for filtered case volume and turnaround metrics
- chart sections for:
  - cases by status
  - cases over time
  - cases by institution
  - practitioner workload
- dashboard-specific filters for range, date window, institution, and practitioner
- `GET /admin/dashboard-report.pdf` to export the dashboard slice as PDF
- `POST /settings/report` to manage organisation-specific report header/footer text used in generated reports
- `GET /admin.events.csv` for case event export in addition to the main case CSV export

## Data Model Notes

Important current tables/entities visible in code:

- `users`
- `organisations`
- `memberships`
- `institutions`
- `protocols`
- `cases`
- `case_events`
- `radiologist_profiles`
- `notify_events`
- settings/config storage used for report header/footer values

The code still carries compatibility logic for older single-tenant and legacy-role schemas, but active permissions are now organisation-aware.

## File And Code Layout

| Path | Current role |
|---|---|
| `app/main.py` | Main FastAPI app, auth, routing, business logic, reporting, migrations/bootstrap |
| `app/security.py` | Security helpers used by the app |
| `app/referral_ingest.py` | Referral parsing support |
| `templates/landing.html` | Public role-selection landing page |
| `templates/login.html` | Role-aware sign-in page |
| `templates/mfa_verify.html` | MFA verification step |
| `templates/home.html` | Admin workspace/dashboard |
| `templates/radiologist_dashboard.html` | Practitioner workspace |
| `templates/settings.html` | Organisation settings and report settings |
| `templates/owner_dashboard.html` | Owner/superuser overview |
| `templates/owner_organisation_edit.html` | Owner organisation detail and user management |
| `scripts/run-local.ps1` | Local app runner |
| `scripts/setup-test-env.ps1` | Test environment bootstrap |
| `scripts/run-test-local.ps1` | Isolated local test runner |

## Deployment Workflow In Repo

The GitHub workflow configuration shows the current branch-to-environment path:

- push to `develop` -> `.github/workflows/deploy-staging.yml` -> Azure Web App `lumosradflow-staging`
- push to `main` -> `.github/workflows/deploy-production.yml` -> Azure Web App `lumosradflow-prod`

There is also a manual `deploy.ps1` that builds/pushes a container image and restarts an Azure app named `Lumosradflow`. The repo does not fully explain whether that script is a legacy/manual production path or a parallel deployment path, so treat it as a separately maintained manual option unless the infrastructure owner confirms otherwise.
