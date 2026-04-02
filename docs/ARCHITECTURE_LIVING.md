# Architecture Reference (Living Document)

Last updated: 2026-04-02
Owner: Product/Engineering
Status: Active

## Purpose
This document captures the current architecture of the Vetting App with practical implementation detail and review notes.

## 1. Context Diagram (Logical)
Client Browser
-> FastAPI Web App (routes, auth, workflow logic)
-> Data Layer (SQLite or PostgreSQL)
-> File Storage (Local uploads or Azure Blob)
-> Optional SMTP service

## 2. Application Layers
Presentation layer:
- Server-side rendered HTML via Jinja templates.
- Static assets served from `/static`.

Application layer:
- FastAPI route handlers and middleware in `app/main.py`.
- Domain logic currently co-located with route/controller logic.

Data access layer:
- Environment-driven switch between SQLite and SQLAlchemy engine.
- SQL statements are predominantly inline in route/helper functions.

Integration layer:
- Azure Blob SDK wrappers for upload/download/exists.
- SMTP email sending utility and notification route usage.

## 3. Deployment Architecture
Build path:
- Docker image builds from `Dockerfile`.
- Dependencies installed from `requirements.txt`.

Release path:
- `deploy.ps1` performs ACR login, image build/push, App Service restart.

Runtime:
- Azure App Service pulls latest image from ACR.
- App binds on `$PORT`.

## 4. Security Architecture
AuthN:
- Password hash verification with PBKDF2-HMAC SHA256.
- Session cookie managed via SessionMiddleware.

AuthZ:
- Route-level guards (`require_admin`, `require_radiologist`, `require_superuser`).
- Membership-derived org context for org-scoped access.

Security middleware:
- No-cache response policy middleware.
- X-Robots-Tag noindex middleware.

Security caution points:
- Ensure secure session cookie policy in production.
- Prevent production use of default app secret.
- Restrict diagnostic endpoints to trusted context.

## 5. Data Architecture
Primary operational tables:
- `cases`
- `institutions`
- `radiologists`
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

Multi-tenant model:
- org_id scoped records are implemented in schema and queries.
- Full router-level multi-tenant UX flow currently disabled/commented.

## 6. Case Lifecycle Architecture
State-driven workflow model:
- Submit -> Pending -> Vetted/Rejected -> Optional Reopened.

Target intake extension:
- Manual/admin submission remains the phase 1 primary path.
- Phase 2 introduces intake adapters that normalize inbound referrals into a shared draft-case review flow.
- Draft cases are reviewed, amended, and approved by admin before entering the active clinical workflow.

Actors:
- Admin: intake, edit, assign, reopen, report.
- Radiologist: review and decision.

Event model:
- Case and notification events provide trace history.

## 7. Document and File Handling
Upload flow:
- Case files saved to local upload path or blob storage.
- Access endpoints support download/inline rendering where allowed.

Parser trial:
- Dedicated referral trial route parses uploaded docs for field prefill.
- Designed as controlled/test capability, not fully promoted production default.

Planned intake and attachment model:
- Intake sources may include secure email, portal referral submission, and external system messages such as RIS/PACS or HL7-based feeds.
- All inbound documents should be stored against the draft or active case record with source metadata preserved.
- Original source payload, extracted fields, and approval history should remain traceable for audit and operational review.

Retention:
- TTL constants exist for referral files and case records.
- Verify actual purge scheduling and enforcement behavior operationally.

## 8. Operational Architecture
Environment-configurable behavior:
- DB backend, storage backend, SMTP, superadmin bootstrap, base URL.

Health endpoints:
- `/health`, `/healthz` for liveness.

Current observability maturity:
- Basic startup/log print diagnostics.
- No standardized telemetry architecture documented.

## 9. Target Intake Architecture (Phase 2 Direction)
Logical target flow:
- Intake channels: secure email inbox, portal referral form, and direct external system integration.
- Intake adapters: channel-specific handlers for email, form, HL7, RIS, or PACS-originated payloads.
- Normalization and validation: map inbound payloads to a common draft-case schema and flag uncertainty.
- Draft review queue: admin checks extracted details, edits as needed, and approves or rejects.
- Active workflow: approved drafts become standard cases and continue through assignment and vetting lifecycle.

Design principles:
- Different intake channels should converge on one internal draft-case model.
- Automation should create draft cases, not directly create fully live cases.
- Source type, original payload, attachments, and approval actions should be auditable.
- The common workflow should allow phase-by-phase rollout of adapters without redesigning the core case model.

## 10. Architecture Weak Areas
1. Monolithic application file (`app/main.py`) is too broad in responsibility.
2. Runtime schema mutation and migration scripts are mixed.
3. Partial multi-tenant activation creates architecture ambiguity.
4. Incomplete production hardening around config defaults and diagnostics.
5. Integration behavior (SMTP/blob) depends heavily on environment correctness.

## 11. Architecture Improvement Plan
Phase 1: Hardening
- Enforce secure prod configuration and endpoint restrictions.
- Add readiness checks and startup validation for required dependencies.

Phase 2: Modularization
- Split routes by domain (`auth`, `cases`, `settings`, `admin`, `radiologist`).
- Introduce service layer for business logic and storage abstraction.
- Introduce a draft-case intake service and normalization boundary so new channels plug into a shared workflow.

Phase 3: Data discipline
- Standardize migrations and remove runtime schema drift patterns.
- Add explicit DB compatibility policy and migration validation in CI.
- Add explicit source metadata, draft review, and intake audit structures where required.

Phase 4: Tenant maturity
- Enable complete tenant router flow behind controlled flag.
- Add tenant isolation test suite and policy assertions.

Phase 5: External intake expansion
- Add secure email-to-draft intake for approved client workflows.
- Add portal-based referral intake for structured submission.
- Add direct system adapters for RIS/PACS or HL7-style message ingestion where client environments support it.

## 12. Non-Functional Targets (Suggested)
- Availability: >= 99.9% app uptime target.
- RPO: <= 24h, RTO: <= 4h (define backup/restore runbook).
- Security: periodic authz tests and secret rotation schedule.
- Performance: define p95 endpoint latency targets per major route.

## 13. Update Log
- 2026-04-02: Added target intake architecture and phased draft-case expansion model.
- 2026-03-08: Initial living architecture reference created.

## 14. Update Template (append on each revision)
Date:
Author:
Architecture area changed:
Before:
After:
Impact:
Validation done:
Open concerns:
