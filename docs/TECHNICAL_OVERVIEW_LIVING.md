# Technical Overview (Living Document)

Last updated: 2026-04-05
Owner: Product/Engineering
Status: Active

## Purpose

This document is a detailed, continuously updated technical reference for RadFlow. It is intended for internal engineering, external reviewers, and independent consultants.

## 1. System Summary

RadFlow is a FastAPI-based web platform for radiology referral intake, vetting workflow management, organisation administration, and operational reporting.

Primary outcomes:

- standardized case intake and assignment
- role-based workflow for owners, admins, practitioners, and coordinators
- case status lifecycle visibility and export
- organisation-aware data isolation using `organisations` and `memberships`
- clear path to phase 2 intake automation through draft-case review

## 2. Technology Stack

Backend:

- Python 3.11 container runtime in `Dockerfile`; GitHub Actions currently sets up Python 3.12 for Azure code deployment
- FastAPI application server
- Jinja2 templates for server-side rendering

Data:

- SQLite default for local/dev (`DB_PATH`)
- PostgreSQL via `DATABASE_URL` for hosted/production use
- SQLAlchemy used when `DATABASE_URL` is present

Storage:

- local filesystem (`UPLOAD_DIR`) fallback
- Azure Blob Storage optional (`AZURE_STORAGE_CONNECTION_STRING`)

Integrations:

- SMTP for password reset and practitioner notification email flow
- optional iRefer API integration settings present

## 3. Runtime and Hosting

Container/runtime:

- base image: `python:3.11-slim`
- `Dockerfile` entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`
- `startup.sh` provides a Gunicorn + Uvicorn-worker startup path

Hosting target:

- Azure App Service is the active deployment target in repo workflows
- GitHub Actions deploys code packages from:
  - `develop` to `lumosradflow-staging`
  - `main` to `lumosradflow-prod`
- `deploy.ps1` also exists as a manual Azure container deployment path, but its target app naming does not match the current GitHub Actions workflow names

## 4. Main Application Structure

Core code paths:

- `app/main.py`: primary application module containing routes, DB helpers, auth/session logic, and business workflows
- `app/referral_ingest.py`: referral document parsing logic
- `templates/`: UI templates for owner, admin, settings, submit, and practitioner flows
- `static/`: CSS/images/JS assets

Current architectural characteristic:

- monolithic application module with mixed concerns in one main file

## 5. Data and Persistence Model

Primary entities:

- `cases`
- `institutions`
- `radiologists`
- `radiologist_profiles`
- `users`
- `memberships`
- `protocols`
- `case_events`
- `notify_events`
- `password_reset_tokens`
- `organisations`

Data access pattern:

- runtime path switches between SQLite and PostgreSQL using environment detection
- table/column existence checks and conditional SQL are used to handle schema variation

## 6. Authentication and Authorization

Authentication:

- username/password verification with PBKDF2-HMAC SHA256 hashing
- session-based auth using Starlette `SessionMiddleware`
- session idle timeout currently set to 20 minutes
- optional TOTP MFA for account enrollment and sign-in step-up

Authorization:

- role checks via helpers like `require_admin`, `require_radiologist`, and `require_superuser`
- organisation context is resolved from memberships where available
- superuser/owner path is active

Password reset:

- token-based reset flow with `password_reset_tokens` table and reset endpoints

Current MFA behavior:

- `POST /login` redirects MFA-enabled users to `/login/mfa`
- `/account` supports MFA enrollment begin/enable/disable flows
- admin-capable users marked `mfa_required` are blocked from admin access until enrollment is completed

## 7. Workflow Overview

Owner flow:

1. superuser signs in and lands on `/owner`
2. creates or edits organisations
3. seeds or manages organisation users, including MFA requirement flags and password resets

Admin flow:

1. submit case (`/submit`) with optional file attachment
2. manage and filter dashboard (`/admin`)
3. assign practitioner and update case details
4. reopen/edit as needed

Practitioner flow:

1. view queue/dashboard
2. open case and vet
3. record decision/comment
4. case transitions through status lifecycle

Reporting and outputs:

- CSV export (`/admin.csv`)
- case events CSV export (`/admin.events.csv`)
- dashboard PDF export (`/admin/dashboard-report.pdf`)
- case PDF generation (`/case/{case_id}/pdf`)
- organisation-specific report header/footer settings through `/settings/report`

Planned phase 2 intake flow:

1. referral arrives through secure email, portal submission, or external system message
2. intake adapter parses payload and stores original source content/attachments
3. normalization layer maps inbound fields into a common draft-case model
4. admin reviews, amends, and approves the draft case
5. approved draft becomes a normal active case and continues through assignment/vetting

## 8. Referral Parser Trial Feature

Feature path:

- `/submit/referral-trial`
- `/submit/referral-trial/parse`
- `/submit/referral-trial/create`

Capabilities:

- parses text-based documents
- extracts fields to prefill case creation flow

Known limitation:

- OCR for scanned image-heavy documents is not fully enabled for production workflow

## 9. Configuration (Environment Variables)

Key variables:

- `APP_SECRET`
- `APP_BASE_URL`
- `DATABASE_URL`
- `DB_PATH`
- `UPLOAD_DIR`
- `PORT`
- `AZURE_STORAGE_CONNECTION_STRING`
- `REFERRAL_BLOB_CONTAINER`
- `REFERRAL_FILE_TTL_DAYS`
- `CASE_RECORD_TTL_DAYS`
- `ALLOW_DIAGNOSTIC_ENDPOINT`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- `IREFER_API_KEY`

Operational note:

- production should not run with default secret values

## 10. Observability and Operations

Available:

- health endpoints: `/health`, `/healthz`
- console logging with startup configuration output

Gaps:

- no dedicated structured logging pipeline documented
- no explicit metrics/tracing stack documented in repo
- readiness probes are not separated from liveness checks

## 11. Security Posture (Current)

Controls present:

- password hashing with PBKDF2
- session timeout
- role-based endpoint guards
- TOTP MFA support and MFA-required enforcement for admin-capable accounts
- no-cache and no-index response headers middleware

Areas to review/harden:

- enforce strong secret handling and fail-fast in production on insecure defaults
- harden session cookie flags for production
- restrict diagnostic/admin-only endpoints

## 12. Known Technical Debt and Risks

- large monolithic `main.py` increases change risk and testing complexity
- mixed migration strategy: runtime schema changes plus migration scripts
- coexistence of legacy and current permission paths increases complexity
- legacy helper scripts include insecure credential patterns and should be sanitized

## 13. Recommended Roadmap (Technical)

Short term:

- enforce production security defaults and endpoint hardening
- gate trial parser by explicit feature flag
- add readiness endpoint with dependency checks

Medium term:

- split monolith into domain routers/services
- move fully to migration-led schema lifecycle
- add draft-case status handling and source metadata to support intake expansion

Long term:

- add structured observability
- expand parser capability with production-grade OCR pipeline
- add adapter-based intake channels for secure email, portal referral forms, and external system messages

## 14. Independent Reviewer Checklist

- auth/session hardening and secret management
- authorization boundary tests for role and org isolation
- migration and rollback safety
- storage durability and retention behavior
- error handling and incident recoverability
- scalability bottlenecks in monolith and DB access layer

## 15. Update Log

- 2026-04-05: Updated for owner routes, MFA flow, current Azure deploy workflow, and admin reporting surface
- 2026-04-02: Added draft-case intake roadmap and multi-channel referral architecture direction
- 2026-03-08: Initial living version created
