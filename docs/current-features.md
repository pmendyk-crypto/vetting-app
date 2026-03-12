# Current Features

| Feature | What it does | Status guess | Code location |
|---|---|---|---|
| User authentication and session login | Handles sign-in/sign-out, session timeout, and role-based access entry. | Keep | `app/main.py, app/security.py, templates/login.html` |
| Password reset workflow | Forgot/reset password token flow with email dispatch when SMTP is configured. | Keep | `app/main.py, templates/forgot_password.html, templates/reset_password.html` |
| Admin dashboard and case monitoring | Central admin dashboard for case lifecycle visibility and filtering. | Keep | app/main.py (`/admin`), templates/home.html |
| Case submission and intake | Creates new cases with patient and referral details. | Keep | app/main.py (`/submit`, `/intake/{org_id}`), templates/submit.html |
| File upload and attachment storage | Stores referral files locally or in blob storage. | Keep | `app/main.py attachment/storage helpers, uploads/` |
| Radiologist queue and vetting workflow | Radiologists review assigned cases and submit vetting decisions. | Keep | app/main.py (`/radiologist`, `/vet/{case_id}`), templates/vet.html |
| Case reopen/reassign | Admin can reopen and reassign cases. | Keep | `app/main.py admin case routes` |
| Settings/master data management | Manage institutions, protocols, users, and presets. | Keep | app/main.py (`/settings*`), templates/settings.html |
| Attachment download/inline viewing | Authorized users can retrieve/view case attachments. | Keep | app/main.py (`/case/{case_id}/attachment*`) |
| PDF generation | Generates case and timeline PDF outputs. | Keep | app/main.py (`/case/{case_id}/pdf`, timeline PDF route) |
| CSV exports | Exports case and event datasets. | Keep | app/main.py (`/admin.csv`, `/admin.events.csv`) |
| Referral parser trial | Parses referral docs and prefills case fields before create. | Review | app/main.py (`/submit/referral-trial*`), app/referral_ingest.py |
| iRefer search | Guideline lookup endpoint integration. | Review | app/main.py (`/irefer/search`) |
| Radiologist notification email | Admin can send outbound notifications to radiologists. | Simplify | app/main.py (`/admin/notify-radiologist`) |
| Superuser org governance | Org/user/billing level management routes. | Disable | app/main.py (`/mt/*`, `/super/*`) |
| Alternative multitenant router module | Separate APIRouter tenant flows exists but appears not mounted. | Disable | `app/routers/multitenant.py + commented include in app/main.py` |
| Diagnostic and health endpoints | Liveness and schema inspection endpoints. | Simplify | app/main.py (`/health`, `/healthz`, `/diag/schema`) |

## Operating Scope Notes
- Current runtime policy is single-client mode.
- Multi-tenant platform workflows are paused and should remain disabled from end-user UI.
- Organisation-related schema remains for compatibility and potential future reactivation.
