# Technical Overview (Living Document)

Last updated: 2026-04-02
Owner: Product/Engineering
Status: Active

## Purpose
This document is a detailed, continuously updated technical reference for the Vetting App. It is intended for internal engineering, external reviewers, and independent consultants.

## 1. System Summary
The Vetting App is a FastAPI-based web platform for radiology referral intake, vetting workflow management, and operational tracking.

Primary outcomes:
- Standardized case intake and assignment.
- Role-based clinical workflow for admins and radiologists.
- Case status lifecycle visibility and export.
- Organization-aware data isolation model (partially enabled multi-tenant model).
- Clear path to phase 2 intake automation through draft-case review.

## 2. Technology Stack
Backend:
- Python 3.11+ runtime in container.
- FastAPI application server (`uvicorn`).
- Jinja2 templates for server-side rendering.

Data:
- SQLite default for local/dev (`DB_PATH`).
- PostgreSQL via `DATABASE_URL` for hosted/production use.
- SQLAlchemy used when `DATABASE_URL` is present.

Storage:
- Local filesystem (`UPLOAD_DIR`) fallback.
- Azure Blob Storage optional (`AZURE_STORAGE_CONNECTION_STRING`).

Integrations:
- SMTP for email notifications and password reset email flow.
- Optional iRefer API integration settings present.

## 3. Runtime and Hosting
Container:
- Base image: `python:3.11-slim`.
- Entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`.

Hosting target:
- Azure App Service (container deployment) is used in current workflow.
- Image push to Azure Container Registry via `deploy.ps1`.

## 4. Main Application Structure
Core code paths:
- `app/main.py`: primary application module containing routes, DB helpers, auth/session logic, and business workflows.
- `app/referral_ingest.py`: referral document parsing logic.
- `templates/`: UI templates (admin, submit, settings, radiologist workflows).
- `static/`: CSS/images/JS assets.

Current architectural characteristic:
- Monolithic application module with mixed concerns in one main file.

## 5. Data and Persistence Model
Primary entities (high level):
- `cases`
- `institutions`
- `radiologists`
- `users`
- `memberships`
- `protocols`
- `case_events`
- `notify_events`
- `password_reset_tokens`
- `organisations` (multi-tenant model)

Data access pattern:
- Runtime path switches between SQLite and PostgreSQL using environment detection.
- Table/column existence checks and conditional SQL are used to handle schema variation.

## 6. Authentication and Authorization
Authentication:
- Username/password verification with PBKDF2-HMAC SHA256 hashing.
- Session-based auth using Starlette `SessionMiddleware`.
- Session idle timeout currently set to 20 minutes.

Authorization:
- Role checks via helpers like `require_admin` and `require_radiologist`.
- Organization context resolved from memberships where available.
- Superuser path is supported.

Password reset:
- Token-based reset flow with `password_reset_tokens` table and reset endpoints.

## 7. Workflow Overview
Admin flow:
1. Submit case (`/submit`) with optional file attachment.
2. Manage and filter dashboard (`/admin`).
3. Assign radiologist and update case details.
4. Reopen/edit as needed.

Radiologist flow:
1. View queue/dashboard.
2. Open case and vet.
3. Record decision/comment.
4. Case transitions through status lifecycle.

Reporting and outputs:
- CSV export (`/admin.csv`).
- PDF generation (`/case/{case_id}/pdf`).

Planned phase 2 intake flow:
1. Referral arrives through secure email, portal submission, or external system message.
2. Intake adapter parses payload and stores original source content/attachments.
3. Normalization layer maps inbound fields into a common draft-case model.
4. Admin reviews, amends, and approves the draft case.
5. Approved draft becomes a normal active case and continues through assignment/vetting.

## 8. Referral Parser Trial Feature
Feature path:
- `/submit/referral-trial`
- `/submit/referral-trial/parse`
- `/submit/referral-trial/create`

Capabilities:
- Parses text-based documents (PDF, DOCX, TXT-like formats).
- Extracts fields to prefill case creation form.

Known limitation:
- OCR for scanned image-heavy documents is not fully enabled for production workflow.

Strategic fit:
- Current parser capability aligns with a future draft-case intake workflow.
- Parser outputs should eventually feed a draft review queue rather than bypass manual validation.

## 9. Configuration (Environment Variables)
Key variables:
- `APP_SECRET`
- `DATABASE_URL`
- `DB_PATH`
- `UPLOAD_DIR`
- `PORT`
- `AZURE_STORAGE_CONNECTION_STRING`
- `REFERRAL_BLOB_CONTAINER`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- `AUTO_PROVISION_SUPERADMIN`, `SUPERADMIN_USERNAME`, `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD`

Operational note:
- Production should not run with default secret values.

## 10. Observability and Operations
Available:
- Health endpoints: `/health`, `/healthz`.
- Console logging with startup configuration output.

Gaps:
- No dedicated structured logging pipeline documented.
- No explicit metrics/tracing stack documented in repo.
- Readiness probes are not separated from liveness checks.

## 11. Security Posture (Current)
Controls present:
- Password hashing with PBKDF2.
- Session timeout.
- Role-based endpoint guards.
- No-cache and no-index response headers middleware.

Areas to review/harden:
- Enforce strong secret handling and fail-fast in production on insecure defaults.
- Harden session cookie flags for production (`Secure`, strict policy decisions).
- Restrict diagnostic/admin-only endpoints.

## 12. Known Technical Debt and Risks
- Large monolithic `main.py` increases change risk and testing complexity.
- Mixed migration strategy (runtime schema changes plus migration scripts).
- Partial multi-tenant enablement can create behavior ambiguity.
- Legacy helper scripts include insecure credential patterns and should be sanitized.

## 13. Recommended Roadmap (Technical)
Short term (0-4 weeks):
- Enforce production security defaults and endpoint hardening.
- Gate trial parser by explicit feature flag.
- Add readiness endpoint with dependency checks.

Medium term (1-2 quarters):
- Split monolith into domain routers/services.
- Move fully to migration-led schema lifecycle.
- Complete and test true multi-tenant router integration.
- Add draft-case status handling and source metadata to support intake expansion.

Long term:
- Add structured observability (logs, metrics, traces).
- Expand parser capability with production-grade OCR pipeline.
- Add adapter-based intake channels for secure email, portal referral forms, and RIS/PACS or HL7-style system messages.

## 14. Independent Reviewer Checklist
Use this checklist for external IT review:
- Auth/session hardening and secret management.
- Authorization boundary tests (role and org isolation).
- Migration and rollback safety.
- Storage durability and retention behavior.
- Error handling and incident recoverability.
- Scalability bottlenecks in monolith and DB access layer.

## 15. Update Log
- 2026-04-02: Added draft-case intake roadmap and multi-channel referral architecture direction.
- 2026-03-08: Initial living version created.

## 16. Update Template (append on each revision)
Use this format for future updates:

Date:
Author:
Scope:
Changes:
Risks introduced:
Validation done:
Next actions:
