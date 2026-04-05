# Pilot Live Data Readiness

Last updated: 2026-04-05
Owner: Product/Engineering
Status: Working checklist

## Purpose

This document is a practical readiness checklist for a pilot that will use live patient data in the UK.

It separates:

- changes that must be made in the app or production technical environment
- governance, assurance, and organisational work that must also be completed

It is intentionally stricter than a normal internal pilot checklist because the proposed pilot will use live patient-identifiable data.

## Important Scope Note

This checklist is based on:

- the current repository code
- the current documentation in this repository
- UK/NHS-facing security and governance expectations already identified in the project documents

It does not confirm the real state of the current production environment.

If staging is newer than production, production may still have older gaps that are not visible from the codebase alone. Treat every production control as needing explicit verification before pilot sign-off.

## 1. Overall Position

Current position from the codebase:

- the app has a reasonable prototype/pilot baseline
- it is not yet safe to assume full readiness for live patient data without additional hardening and governance work

Recommendation:

- do not start a live-data pilot until every item marked `Must complete before pilot` is either completed or formally risk-accepted by the accountable stakeholders

## 2. Must Complete In The App Or Production Technical Environment

These are the controls that must exist in the running production or pilot environment and, where needed, in the application itself.

### A. Secrets and configuration

#### Must complete before pilot

- Remove all unsafe fallback secrets from production use.
  - `APP_SECRET` must never fall back to `dev-secret-change-me`.
- Remove or disable any unsafe bootstrap/default admin password behavior in production.
- Store production secrets outside code and local env files.
  - Use Azure Key Vault or equivalent.
- Fail startup in production if required secure settings are missing.

#### Already partially in place

- The app already warns or errors for missing production settings in some paths.
- `APP_SECRET` and `DATABASE_URL` checks exist in code.

#### Gap

- The presence of fallback values means the protection is not strong enough until production is configured and verified correctly.

### B. Storage and database model

#### Must complete before pilot

- Use Azure PostgreSQL only for the live-data pilot database.
- Use Azure Blob Storage only for live referral attachments.
- Disable or operationally prohibit SQLite and local file storage in the pilot environment.
- Confirm encryption at rest is enabled for the managed database and blob storage.
- Define backup, restore, retention, and deletion procedures for live data.

#### Already partially in place

- The app supports PostgreSQL and Azure Blob paths.

#### Gap

- SQLite and local uploads are still valid runtime options in the app.
- That is acceptable for local development, but not as a live-data pilot pattern.

### C. Transport and web hardening

#### Must complete before pilot

- Enforce HTTPS for all pilot traffic.
- Confirm HSTS is active in the production/pilot path.
- Confirm secure cookie settings are correct for production.
- Confirm cookie policy is appropriate for authenticated healthcare workflows.
- Restrict allowed hosts to the real production hostnames.
- Disable or tightly restrict diagnostic endpoints such as `/diag/schema`.

#### Already partially in place

- HSTS logic exists in app code for production.
- Trusted host support exists.
- No-cache and no-index headers exist.

#### Gap

- Secure cookie hardening is not yet clearly complete enough from code review alone.
- Production host restriction and HTTPS enforcement need deployment verification.

### D. Authentication and access control

#### Must complete before pilot

- Require MFA for all privileged/admin-capable accounts.
- Decide whether practitioners must also use MFA for the pilot.
- Review and verify all owner/admin/practitioner/coordinator role assignments in the pilot environment.
- Verify no stale production accounts remain with inappropriate access.
- Define joiner/mover/leaver access processes for pilot users.

#### Already in place

- MFA exists in the app.
- MFA can be required.
- Organisation-aware role checks exist.

#### Gap

- MFA is available, but it still needs policy enforcement and production rollout discipline.

### E. Request integrity and abuse protection

#### Must complete before pilot

- Add CSRF protection for state-changing form submissions.
- Replace in-memory rate limiting with a shared production-grade control.
- Confirm brute-force protection works across instances, not just inside one process.

#### Already partially in place

- Login and MFA attempt rate limiting exists.

#### Gap

- Current rate limiting is in-memory only.
- No explicit CSRF protection is evident in the current app.

### F. Logging, audit, and monitoring

#### Must complete before pilot

- Ensure access, change, export, and security-relevant events are logged appropriately.
- Ensure logs do not contain patient data, reset content, or sensitive secrets.
- Add operational monitoring and alerting for authentication failures, system errors, and suspicious activity.
- Define log retention and access controls.

#### Already partially in place

- Case events and related audit concepts exist.

#### Gap

- Full production security monitoring and audit coverage are not yet clearly documented or verified.

### G. Data protection by design

#### Must complete before pilot

- Minimise the patient-identifiable data captured to what is genuinely needed for the pilot.
- Confirm retention periods for referral files and records.
- Confirm deletion and archival behavior is controlled and documented.
- Decide whether any especially sensitive fields require field-level encryption beyond platform encryption.

#### Already partially in place

- Retention-related settings exist in config.

#### Gap

- A complete documented retention/deletion operating model is not yet visible.
- No field-level encryption strategy is visible in the app.

## 3. Must Complete In Governance, Assurance, And Organisational Work

These items are not solved by code changes alone. They still must be complete before a live-data pilot.

### A. Data protection and legal basis

#### Must complete before pilot

- Confirm whether Lumos Lab is acting as processor, controller, or joint controller for the pilot.
- Document the Article 6 lawful basis.
- Document the Article 9 condition for special category health data.
- Complete a DPIA and have it reviewed/approved.
- Put the correct controller-processor agreement in place if applicable.
- Define privacy notice responsibilities and data subject rights handling.

### B. NHS / customer assurance

#### Must complete before pilot

- Confirm whether DSPT is required for the intended pilot arrangement and complete it where applicable.
- Prepare DTAC evidence for the pilot/customer review process.
- Be ready to explain technical security, data protection, interoperability, usability/accessibility, and clinical safety position.

### C. Clinical safety

#### Must complete before pilot

- Decide whether the product is in scope for DCB0129 and DCB0160 for the intended pilot use.
- If in scope:
  - appoint a Clinical Safety Officer
  - maintain a hazard log
  - produce the clinical risk management file
  - produce the safety case/reporting expected for the deployment context

### D. Operational governance

#### Must complete before pilot

- Create an incident response and breach response process.
- Define who can approve access to live data.
- Define change control for pilot changes.
- Define backup/restore ownership and test it.
- Define support model, escalation path, and business continuity approach.

### E. Secure email and external data exchange

#### Must complete before pilot

- If live patient data will move by email, confirm the route meets the NHS secure email standard.
- If not, restrict the pilot to approved secure portal/system paths only.
- Document the approved inbound and outbound data flows.

## 4. Practical Split: What Engineering Owns vs What Leadership / Governance Owns

### Engineering / product / platform ownership

- secure app configuration
- managed production storage only
- MFA rollout and role review
- CSRF protection
- production-grade rate limiting
- endpoint hardening
- logging/audit improvements
- monitoring and alerting
- retention/deletion implementation details

### Governance / legal / clinical / organisational ownership

- DPIA
- lawful basis and Article 9 condition
- controller/processor position
- contract terms
- DSPT and DTAC readiness
- clinical safety decision and evidence
- incident governance
- secure email approval

## 5. Red / Amber / Green View

### Green: broadly present in code

- password hashing
- session auth
- role-based access model
- MFA capability
- password reset token flow
- Azure-compatible managed storage/database path
- some audit/event foundations

### Amber: partly present but not enough yet

- production config enforcement
- HSTS / trusted host / cookie hardening
- MFA policy rollout
- retention controls
- audit and monitoring maturity

### Red: should be treated as blocking gaps until resolved

- no verified production-only managed storage requirement
- no explicit CSRF protection
- in-memory-only rate limiting
- no completed DPIA in repo/docs
- no completed assurance pack for NHS-facing live-data use
- no confirmed clinical safety position for live-data pilot

## 6. Minimum Go / No-Go Gate For Live Pilot

Recommended minimum go-live gate:

- all production secrets moved to managed secret storage
- no SQLite or local file storage in pilot
- Azure PostgreSQL and Azure Blob verified
- HTTPS, host restriction, and secure cookie policy verified
- `/diag/schema` disabled or tightly restricted
- MFA enforced for admin-capable users
- CSRF protection implemented
- production-grade rate limiting implemented
- logging/monitoring baseline agreed
- DPIA completed
- lawful basis and Article 9 condition documented
- controller/processor contracts in place
- DSPT / DTAC position agreed with the pilot customer
- clinical safety scope decision completed
- secure email path approved or excluded

## 7. Suggested Next Step

Before any live-data pilot decision, run a formal readiness review with three columns:

- Completed
- Must complete before pilot
- Open decision / owner required

Do not treat staging readiness as proof of production readiness unless every production control is separately verified.
