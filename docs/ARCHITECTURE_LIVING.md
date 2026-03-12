# Architecture Reference (Living Document)

Last updated: 2026-03-08
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

## 9. Architecture Weak Areas
1. Monolithic application file (`app/main.py`) is too broad in responsibility.
2. Runtime schema mutation and migration scripts are mixed.
3. Partial multi-tenant activation creates architecture ambiguity.
4. Incomplete production hardening around config defaults and diagnostics.
5. Integration behavior (SMTP/blob) depends heavily on environment correctness.

## 10. Architecture Improvement Plan
Phase 1: Hardening
- Enforce secure prod configuration and endpoint restrictions.
- Add readiness checks and startup validation for required dependencies.

Phase 2: Modularization
- Split routes by domain (`auth`, `cases`, `settings`, `admin`, `radiologist`).
- Introduce service layer for business logic and storage abstraction.

Phase 3: Data discipline
- Standardize migrations and remove runtime schema drift patterns.
- Add explicit DB compatibility policy and migration validation in CI.

Phase 4: Tenant maturity
- Enable complete tenant router flow behind controlled flag.
- Add tenant isolation test suite and policy assertions.

## 11. Non-Functional Targets (Suggested)
- Availability: >= 99.9% app uptime target.
- RPO: <= 24h, RTO: <= 4h (define backup/restore runbook).
- Security: periodic authz tests and secret rotation schedule.
- Performance: define p95 endpoint latency targets per major route.

## 12. Update Log
- 2026-03-08: Initial living architecture reference created.

## 13. Update Template (append on each revision)
Date:
Author:
Architecture area changed:
Before:
After:
Impact:
Validation done:
Open concerns:
