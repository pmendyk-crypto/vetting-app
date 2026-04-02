# App Overview

## What The Application Does
Vetting App is a FastAPI web platform for referral intake, radiology case triage/vetting, and operational management.
It supports admin and radiologist workflows, document/file handling, reporting exports, and organization-aware access controls.

## Workflow (Current)
1. User authenticates and lands in role-specific workflow.
2. Admin creates/ingests cases (`/submit`, optional referral parser trial).
3. Cases move through pending/reopened/vetted/rejected lifecycle.
4. Radiologists review assigned cases and submit decisions (`/vet/{case_id}`).
5. Admins monitor queues, edit/reopen/reassign cases, and export reports (CSV/PDF).
6. Superuser/tenant routes exist for organization-level management and governance.

## Workflow (Planned Phase 2 Intake Expansion)
1. Referrals may arrive through secure email, portal submission, or external system integration.
2. Intake adapters normalize inbound payloads into a shared draft-case structure.
3. Admin reviews, amends, and approves draft cases before they become active cases.
4. Approved cases then follow the standard assignment, vetting, and reporting workflow.

## Tech Stack
- Backend: FastAPI + Starlette middleware
- Frontend: Jinja2 templates + static CSS/JS
- Database: SQLite (default) and PostgreSQL via `DATABASE_URL`
- Data access: SQL-heavy route handlers + helper functions; SQLAlchemy wrapper for Postgres path
- Storage: local filesystem uploads + optional Azure Blob storage
- Reporting: ReportLab for PDF generation; CSV streaming endpoints
- Deployment: Docker container, Azure App Service/ACR script workflow

## Current Product Direction
The application is currently being simplified to support a **single-client deployment**.

Although multi-tenant capabilities exist in the database schema and some routes, these features are not part of the current operational scope and will be disabled or simplified.

The priority is improving:
- security
- maintainability
- operational stability
- code clarity

before expanding the platform further.

## Current Operating Mode
- One active client only.
- No organisation switching in the UI.
- No multi-tenant platform workflows exposed to users.
- Existing organisation-related schema may remain in place for compatibility.
- Multi-tenant expansion is paused until core application stabilization is complete.

## In-Scope Features (Current)
- Authentication
- Case intake
- Radiologist vetting workflow
- Admin dashboard
- File attachments
- PDF generation
- CSV export
- Referral parser trial
- iRefer search
- Radiologist email notifications

## Future Intake Direction
- Secure email-to-draft intake for approved client workflows
- Structured portal referral submission
- RIS/PACS or HL7-style external message intake
- Shared draft review queue with source-aware audit trail
