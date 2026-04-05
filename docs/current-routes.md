# Current Routes

Current mounted `app/main.py` routes verified from code on 2026-04-05.

This inventory covers the live mounted app routes. It does not include unmounted routes from `app/routers/multitenant.py`.

## Route Groups

- Health and diagnostics: `/health`, `/healthz`, `/diag/schema`, `/robots.txt`
- Public auth: `/`, `/login`, `/login/mfa`, `/forgot-password`, `/reset-password`, `/logout`
- Account: `/account`, `/account/edit`, `/account/change-password`, `/account/mfa/*`
- Owner: `/owner`, `/owner/organisations*`
- Admin: `/admin`, `/admin.csv`, `/admin.events.csv`, `/admin/dashboard-report.pdf`, `/admin/notify-radiologist`, `/admin/case/*`
- Practitioner: `/radiologist`, `/vet/{case_id}`
- Settings and presets: `/settings*`, `/api/study-descriptions/by-modality/{modality}`, `/api/protocols/by-study-description/{preset_id}`
- Intake and submission: `/intake/{org_id}`, `/submit`, `/submit/referral-trial*`, `/submitted/{case_id}`
- Attachments and PDFs: `/case/{case_id}/attachment*`, `/case/{case_id}/pdf`
- Integration: `/irefer/search`

## Mounted Routes

| Route | Method | Purpose | Access |
|---|---|---|---|
| `/health` | `GET` | Lightweight health check | Public |
| `/healthz` | `GET` | Lightweight health check | Public |
| `/diag/schema` | `GET` | Schema diagnostics | Public when enabled; otherwise superuser-only |
| `/robots.txt` | `GET` | Prevent indexing | Public |
| `/` | `GET` | Landing page / redirect for signed-in users | Public |
| `/login` | `GET` | Sign-in page | Public |
| `/login` | `POST` | Credential login step | Public |
| `/login/mfa` | `GET` | MFA verification page | Pending MFA session |
| `/login/mfa` | `POST` | MFA verification submit | Pending MFA session |
| `/forgot-password` | `GET` | Password reset request page | Public |
| `/forgot-password` | `POST` | Create password reset request | Public |
| `/reset-password` | `GET` | Password reset form | Public with token |
| `/reset-password` | `POST` | Reset password using token | Public with token |
| `/logout` | `GET` | Clear session and sign out | Authenticated |
| `/account` | `GET` | Account profile and MFA management | Authenticated |
| `/account/edit` | `POST` | Update own profile | Authenticated |
| `/account/change-password` | `POST` | Change own password | Authenticated |
| `/account/mfa/begin` | `POST` | Start MFA enrollment | Authenticated |
| `/account/mfa/enable` | `POST` | Confirm MFA enrollment | Authenticated |
| `/account/mfa/disable` | `POST` | Disable MFA | Authenticated |
| `/owner` | `GET` | Owner dashboard | Superuser |
| `/owner/organisations` | `POST` | Create organisation and initial admin | Superuser |
| `/owner/organisations/{org_id}` | `GET` | Owner organisation detail page | Superuser |
| `/owner/organisations/{org_id}` | `POST` | Update organisation settings | Superuser |
| `/owner/organisations/{org_id}/users/add` | `POST` | Add organisation user | Superuser |
| `/owner/organisations/{org_id}/users/{user_id}/edit` | `POST` | Edit organisation user | Superuser |
| `/owner/organisations/{org_id}/users/{user_id}/reset-password` | `POST` | Reset organisation user password | Superuser |
| `/owner/organisations/{org_id}/users/{user_id}/delete` | `POST` | Delete organisation user | Superuser |
| `/owner/organisations/{org_id}/institutions/{inst_id}/delete` | `POST` | Delete institution from organisation | Superuser |
| `/owner/organisations/{org_id}/delete` | `POST` | Delete organisation | Superuser |
| `/admin` | `GET` | Admin dashboard and worklist | Admin or superuser |
| `/admin.csv` | `GET` | Export current admin worklist slice | Admin or superuser |
| `/admin/dashboard-report.pdf` | `GET` | Export dashboard report PDF | Admin or superuser |
| `/admin.events.csv` | `GET` | Export case events CSV | Admin or superuser |
| `/admin/notify-radiologist` | `GET` | Practitioner notification screen | Admin or superuser |
| `/admin/notify-radiologist` | `POST` | Send practitioner notification | Admin or superuser |
| `/admin/case/{case_id}` | `GET` | Admin case detail | Admin or superuser |
| `/admin/case/{case_id}/timeline.pdf` | `GET` | Case timeline PDF | Admin or superuser |
| `/admin/case/{case_id}/timeline.csv` | `GET` | Case timeline CSV | Admin or superuser |
| `/admin/case/{case_id}/edit` | `GET` | Case edit page | Admin or superuser |
| `/admin/case/{case_id}/edit` | `POST` | Save case edits | Admin or superuser |
| `/admin/case/{case_id}/assign-radiologist` | `POST` | Assign practitioner | Admin or superuser |
| `/admin/case/{case_id}/reopen` | `GET` | Reopen form | Admin or superuser |
| `/admin/case/{case_id}/reopen` | `POST` | Reopen case | Admin or superuser |
| `/radiologist` | `GET` | Practitioner dashboard and queue | Practitioner or superuser |
| `/settings` | `GET` | Organisation settings | Admin or superuser |
| `/settings/report` | `POST` | Save report header/footer text | Admin or superuser |
| `/settings/institution/add` | `POST` | Add institution | Admin or superuser |
| `/settings/institution/edit/{inst_id}` | `POST` | Edit institution | Admin or superuser |
| `/settings/institution/delete/{inst_id}` | `POST` | Delete institution | Admin or superuser |
| `/settings/radiologist/add` | `POST` | Add practitioner profile | Admin or superuser |
| `/settings/radiologist/delete` | `POST` | Delete practitioner profile | Admin or superuser |
| `/settings/radiologist/edit/{name}` | `GET` | Practitioner profile edit page | Admin or superuser |
| `/settings/radiologist/update` | `POST` | Save practitioner profile | Admin or superuser |
| `/settings/protocol/add` | `POST` | Add protocol | Admin or superuser |
| `/settings/protocol/delete` | `POST` | Delete protocol | Admin or superuser |
| `/settings/protocol/edit/{protocol_id}` | `POST` | Edit protocol | Admin or superuser |
| `/settings/protocol/delete/{protocol_id}` | `POST` | Delete protocol by id | Admin or superuser |
| `/settings/user/add` | `POST` | Add organisation user | Admin or superuser |
| `/settings/user/delete` | `POST` | Delete organisation user | Admin or superuser |
| `/settings/user/edit` | `POST` | Edit organisation user | Admin or superuser |
| `/settings/user/access` | `POST` | Toggle organisation user access | Admin or superuser |
| `/settings/study-descriptions` | `GET` | Study description preset management | Admin or superuser |
| `/settings/study-descriptions/add` | `POST` | Add study description preset | Admin or superuser |
| `/settings/study-descriptions/archive/{preset_id}` | `POST` | Archive study description preset | Admin or superuser |
| `/settings/study-descriptions/restore/{preset_id}` | `POST` | Restore study description preset | Admin or superuser |
| `/settings/study-descriptions/edit/{preset_id}` | `POST` | Edit study description preset | Admin or superuser |
| `/api/study-descriptions/by-modality/{modality}` | `GET` | Fetch study description presets by modality | Admin-context usage |
| `/api/protocols/by-study-description/{preset_id}` | `GET` | Fetch protocol suggestions by preset | Admin-context usage |
| `/intake/{org_id}` | `GET` | Organisation-specific intake form | Public |
| `/intake/{org_id}` | `POST` | Create intake case for organisation | Public |
| `/submit/referral-trial` | `GET` | Referral parser trial page | Admin or superuser |
| `/submit/referral-trial/parse` | `POST` | Parse referral document | Admin or superuser |
| `/submit/referral-trial/create` | `POST` | Create case from parsed referral | Admin or superuser |
| `/submit` | `GET` | Manual case submission page | Admin or superuser |
| `/submit` | `POST` | Create case | Admin or superuser |
| `/submitted/{case_id}` | `GET` | Submission confirmation page | Admin or superuser |
| `/irefer/search` | `GET` | iRefer lookup proxy | Authenticated workflow use |
| `/vet/{case_id}` | `GET` | Practitioner vetting page | Practitioner or superuser |
| `/vet/{case_id}` | `POST` | Save vetting decision | Practitioner or superuser |
| `/case/{case_id}/attachment` | `GET` | Download attachment | Authenticated with case access |
| `/case/{case_id}/attachment/inline` | `GET` | Inline attachment view | Authenticated with case access |
| `/case/{case_id}/attachment/preview` | `GET` | Attachment preview wrapper | Authenticated with case access |
| `/case/{case_id}/pdf` | `GET` | Case PDF | Authenticated with case access |

## Notes

- Older `/mt/*`, `/super/*`, `/select-org`, and `app/routers/multitenant.py` entries are not part of the mounted route set documented here.
- The practical role labels in the current UI are Owner, Admin, Practitioner, and Coordinator.
