# Architecture Reference (Living Document)

Last updated: 2026-04-05
Owner: Product/Engineering
Status: Active

## Purpose

This document captures the current architecture of RadFlow with practical implementation detail and review notes.

## 1. Context Diagram

Client browser
-> FastAPI web app
-> data layer (SQLite or PostgreSQL)
-> file storage (local uploads or Azure Blob)
-> optional SMTP service

## 2. Application Layers

Presentation layer:

- server-side rendered HTML via Jinja templates
- static assets served from `/static`

Application layer:

- FastAPI route handlers and middleware in `app/main.py`
- domain logic currently co-located with route/controller logic

Data access layer:

- environment-driven switch between SQLite and SQLAlchemy engine
- SQL statements are predominantly inline in route/helper functions

Integration layer:

- Azure Blob SDK wrappers for upload/download/exists
- SMTP email sending utility and notification route usage

## 3. Deployment Architecture

Build path:

- dependencies installed from `requirements.txt`
- Azure App Service code deployment is the active repo workflow

Release path:

- `develop` -> staging Azure Web App `lumosradflow-staging`
- `main` -> production Azure Web App `lumosradflow-prod`
- `deploy.ps1` remains as a manual Azure container deployment script

Runtime:

- app binds on `$PORT`
- repo includes direct Uvicorn startup and `startup.sh` Gunicorn startup

## 4. Security Architecture

AuthN:

- password hash verification with PBKDF2-HMAC SHA256
- session cookie managed via `SessionMiddleware`
- optional authenticator-app TOTP MFA with QR enrollment

AuthZ:

- route-level guards: `require_admin`, `require_radiologist`, `require_superuser`
- membership-derived org context for org-scoped access

Security middleware:

- no-cache response policy middleware
- no-index related response headers

Security caution points:

- ensure secure session cookie policy in production
- prevent production use of default app secret
- restrict diagnostic endpoints to trusted context
- keep MFA-required admin accounts enrolled before expecting admin access

## 5. Data Architecture

Primary operational tables:

- `cases`
- `institutions`
- `radiologists`
- `radiologist_profiles`
- `protocols`
- `users`
- `memberships`
- `case_events`
- `notify_events`

Support/control tables:

- `password_reset_tokens`
- `config`
- `audit_logs`
- `organisations`

Organisation-aware model:

- `org_id` scoped records are implemented in schema and queries
- `memberships.org_role` is the active organisation permission model
- owner governance is exposed through `/owner*` routes
- the alternate router-level multitenant UX in `app/routers/multitenant.py` is not the live mounted path

## 6. Case Lifecycle Architecture

State-driven workflow model:

- submit -> pending -> vetted or rejected -> optional reopened

Target intake extension:

- manual/admin submission remains the primary path today
- phase 2 introduces intake adapters that normalize inbound referrals into a shared draft-case review flow
- draft cases are reviewed, amended, and approved by admin before entering the active workflow

Actors:

- Owner: organisation governance
- Admin: intake, edit, assign, reopen, report
- Practitioner: review and decision

Event model:

- case and notification events provide trace history

Reporting model:

- admin dashboard includes metrics, charts, dashboard PDF export, case CSV export, and event CSV export
- report header/footer text is organisation-configurable in settings

## 7. Document and File Handling

Upload flow:

- case files saved to local upload path or blob storage
- access endpoints support download, inline rendering, and preview where allowed

Parser trial:

- dedicated referral trial route parses uploaded docs for field prefill
- designed as controlled/test capability, not fully promoted production default

Retention:

- TTL constants exist for referral files and case records
- actual purge scheduling is not documented in repo code paths reviewed here

## 8. Operational Architecture

Environment-configurable behavior:

- DB backend
- storage backend
- SMTP
- base URL
- diagnostic endpoint enablement

Health endpoints:

- `/health`
- `/healthz`

Current observability maturity:

- basic startup/log diagnostics
- no standardized telemetry architecture documented

## 9. Target Intake Architecture

Logical target flow:

- intake channels: secure email inbox, portal referral form, and direct external system integration
- intake adapters: channel-specific handlers
- normalization and validation: map inbound payloads to a common draft-case schema
- draft review queue: admin checks extracted details, edits as needed, and approves or rejects
- active workflow: approved drafts become standard cases and continue through assignment and vetting

Design principles:

- different intake channels should converge on one internal draft-case model
- automation should create draft cases, not directly create fully live cases
- source type, original payload, attachments, and approval actions should be auditable

## 10. Architecture Weak Areas

1. `app/main.py` is too broad in responsibility.
2. Runtime schema mutation and migration scripts are mixed.
3. Legacy and current permission paths coexist, increasing complexity.
4. Production hardening around config defaults and diagnostics still needs care.
5. Integration behavior depends heavily on environment correctness.

## 11. Architecture Improvement Plan

Phase 1: hardening

- enforce secure prod configuration and endpoint restrictions
- add readiness checks and startup validation for required dependencies

Phase 2: modularization

- split routes by domain
- introduce service layer for business logic and storage abstraction
- introduce a draft-case intake service boundary

Phase 3: data discipline

- standardize migrations and reduce runtime schema drift patterns
- add explicit DB compatibility policy and migration validation in CI

Phase 4: intake expansion

- add secure email-to-draft intake
- add portal-based referral intake
- add direct system adapters where environments support them

## 12. Update Log

- 2026-04-05: Updated deploy architecture, owner-route model, and MFA/reporting notes
- 2026-04-02: Added target intake architecture and phased draft-case expansion model
- 2026-03-08: Initial living architecture reference created
