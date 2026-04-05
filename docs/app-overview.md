# App Overview

## What The Application Does

RadFlow is a FastAPI web application for referral intake, case triage, practitioner vetting, reporting, and organisation management.

The current code supports:

- session-based sign-in with password reset and optional TOTP MFA
- owner, admin, practitioner, and coordinator-style access patterns
- organisation-scoped case management and settings
- admin reporting with CSV and PDF exports
- practitioner notification and referral parser trial flows

## Current Workflow

1. User signs in through `/login`.
2. If MFA is enabled, sign-in continues through `/login/mfa`.
3. If MFA is required but not yet enrolled for an admin-capable user, the user is redirected to `/account` to complete enrollment.
4. Owner users land on `/owner`.
5. Organisation admins land on `/admin`.
6. Practitioners land on `/radiologist`.
7. Admins create or intake cases through `/submit` or `/intake/{org_id}`.
8. Cases move through `pending`, `reopened`, `vetted`, and `rejected` states.
9. Practitioners review assigned cases and submit decisions through `/vet/{case_id}`.
10. Admins monitor dashboards, reopen/edit/reassign cases, notify practitioners, and export dashboard/case data.

## Current Role Model

Operationally, the app now uses:

- Owner
  - backed by `users.is_superuser`
  - cross-organisation access and owner dashboard
- Admin
  - usually backed by `memberships.org_role = org_admin`
  - `radiology_admin` is also treated as admin-capable in code
- Practitioner
  - backed by `memberships.org_role = radiologist`
- Coordinator
  - backed by `memberships.org_role = org_user`

Legacy `users.role` values are still present for compatibility, but the active permission model is organisation-aware.

## Product Direction

The repo is no longer best described as "single-client only". The main application code actively uses `organisations`, `memberships`, owner routes, and organisation-scoped filtering.

The more accurate current position is:

- organisation-aware workflows are active in the main app
- the old alternate multi-tenant router module is not the live path
- owner/superuser governance now happens through `/owner*` routes, not the older `/mt/*` UX
- future intake expansion is still expected to feed a reviewed workflow rather than bypass admin oversight

## In-Scope Features

- authentication, account management, and MFA
- password reset
- owner organisation management
- admin dashboard and reporting
- organisation settings and user management
- practitioner queue and vetting
- public org intake and admin submission
- attachment handling and PDF generation
- referral parser trial
- iRefer lookup
- practitioner notifications

## Planned Intake Direction

- secure email-to-draft intake
- structured portal referral submission
- external system adapters where appropriate
- common reviewable draft-case model with source-aware audit trail
