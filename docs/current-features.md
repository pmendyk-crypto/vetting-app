# Current Features

| Feature | What it does now | Current state | Main code |
|---|---|---|---|
| Session auth and sign-in | Session-based sign-in with role-aware post-login redirects, sliding session timeout, logout, and unauthorized redirects back to login. | Active | `app/main.py`, `templates/landing.html`, `templates/login.html`, `templates/index.html` |
| MFA and account security | Supports authenticator-app TOTP setup, QR enrollment, MFA verification at sign-in, MFA-required enforcement for admin-capable users, and self-service MFA management from `/account`. | Active | `app/main.py`, `templates/mfa_verify.html` |
| Password reset | Forgot/reset password flow with tokenized reset links when SMTP is configured. | Active | `app/main.py`, `templates/forgot_password.html`, `templates/reset_password.html` |
| Owner dashboard | Superuser-only organisation creation and management, including first-admin setup, MFA requirement flags, user management, and org deletion. | Active | `app/main.py` (`/owner*`), `templates/owner_dashboard.html`, `templates/owner_organisation_edit.html` |
| Admin dashboard and reporting | `/admin` combines worklist filtering with dashboard metrics, status/institution/practitioner charts, CSV export, events export, and a PDF dashboard report. | Active | `app/main.py` (`/admin`, `/admin.csv`, `/admin.events.csv`, `/admin/dashboard-report.pdf`), `templates/home.html` |
| Report branding/settings | Organisation-specific report header and footer text can be edited in settings and are used by generated reports. | Active | `app/main.py` (`/settings/report`), `templates/settings.html` |
| Case submission and org intake | Public submission and org-scoped intake create cases with assignment, notes, metadata, and uploaded referral files. | Active | `app/main.py` (`/submit`, `/intake/{org_id}`), `templates/submit.html`, `templates/submitted.html` |
| Practitioner queue and vetting | Practitioners see assigned cases, review details, and submit vetting decisions from `/vet/{case_id}`. | Active | `app/main.py` (`/radiologist`, `/vet/{case_id}`), `templates/radiologist_dashboard.html`, `templates/vet.html` |
| Case reopen and reassignment | Admin users can reopen cases and change assignments/details from admin case routes. | Active | `app/main.py` admin case routes |
| Practitioner notifications | Admin users can send practitioner notifications and log notify events. Email is implemented; SMS currently redirects with `sms_not_configured`. | Active with partial channel support | `app/main.py` (`/admin/notify-radiologist`), `templates/notify_radiologist.html` |
| Settings and master data | Settings supports institutions, protocols, users, practitioner profile data, study description presets, and report settings. | Active | `app/main.py` (`/settings*`), `templates/settings.html` |
| Attachment retrieval and PDFs | Authorized users can download/view attachments and generate case/report PDFs. | Active | `app/main.py` (`/case/{case_id}/attachment*`, `/case/{case_id}/pdf`) |
| Referral parser trial | Trial parsing flow exists to prefill submission data from referral files. | Active, still trial-labelled | `app/main.py` (`/submit/referral-trial*`), `app/referral_ingest.py` |
| iRefer search | iRefer search endpoint exists and is feature-flagged by API key presence. | Active when configured | `app/main.py` (`/irefer/search`) |
| Diagnostic endpoints | Health and diagnostic endpoints exist, with diagnostics gated by config/superuser checks. | Active, limited scope | `app/main.py` (`/health`, `/healthz`, `/diag/schema`) |

## Current Roles And Labels

| Storage field | Stored value | UI label | Practical meaning |
|---|---|---|---|
| `users.is_superuser` | `1` | Owner | Cross-organisation superuser access and owner dashboard |
| `memberships.org_role` | `org_admin` | Admin | Organisation admin |
| `memberships.org_role` | `radiology_admin` | Admin | Also accepted as admin-capable in code |
| `memberships.org_role` | `radiologist` | Practitioner | Practitioner queue/vetting user |
| `memberships.org_role` | `org_user` | Coordinator | Standard organisation user without admin rights |

Legacy `users.role` values remain in code for compatibility and setup flows, but membership roles drive the current organisation permission model.

## Current Scope Notes

- Multi-organisation support is active in the main app through `organisations`, `memberships`, and owner routes.
- The current reporting surface is broader than older docs implied: dashboard PDF, dashboard CSV, and events CSV all exist.
- SMS sending cannot be confirmed as implemented from code; the current notify flow explicitly reports SMS as not configured.
