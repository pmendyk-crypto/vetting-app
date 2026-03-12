# Current Routes

Generated from code decorators. Total routes: 99.

# Route Categories

Authentication
- /login
- /logout
- /forgot-password
- /reset-password

Admin Workflow
- /admin
- /admin/case/*
- /admin.csv
- /admin.events.csv

Case Management
- /submit
- /submitted/{case_id}

Radiologist Workflow
- /radiologist
- /vet/{case_id}

Attachments
- /case/{case_id}/attachment
- /case/{case_id}/attachment/inline

Reporting
- /case/{case_id}/pdf
- CSV exports

Parser Trial
- /submit/referral-trial*

Settings / Configuration
- /settings*

Multi-tenant (legacy / disabled)
- /mt/*
- /super/*
- /select-org

| Route | Method | Function | File | Purpose | Auth |
|---|---|---|---|---|---|
| `/` | `GET` | `landing` | `app/main.py` | Application endpoint | public/unspecified |
| `/account` | `GET` | `account_page` | `app/main.py` | Any authenticated user can view/edit their own profile (name, email, password). | public/unspecified |
| `/account/change-password` | `POST` | `account_change_password` | `app/main.py` | Any authenticated user: change own password with current-password verification. | public/unspecified |
| `/account/edit` | `POST` | `account_edit` | `app/main.py` | Any authenticated user: update own name/email (not role). | public/unspecified |
| `/admin` | `GET` | `admin_dashboard` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin.csv` | `GET` | `admin_dashboard_csv` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin.events.csv` | `GET` | `admin_events_csv` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}` | `GET` | `admin_case_view` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}/assign-radiologist` | `POST` | `assign_radiologist` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}/edit` | `GET` | `admin_case_edit_view` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}/edit` | `POST` | `admin_case_edit_save` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}/reopen` | `GET` | `admin_reopen_case_form` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}/reopen` | `POST` | `admin_reopen_case_submit` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}/timeline.csv` | `GET` | `admin_case_timeline_csv` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/case/{case_id}/timeline.pdf` | `GET` | `admin_case_timeline_pdf` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/notify-radiologist` | `GET` | `notify_radiologist_page` | `app/main.py` | Admin workflow endpoint | admin |
| `/admin/notify-radiologist` | `POST` | `notify_radiologist_send` | `app/main.py` | Admin workflow endpoint | admin |
| `/api/study-descriptions/by-modality/{modality}` | `GET` | `get_study_descriptions` | `app/main.py` | Get study description presets by modality for user's organization (searchable via form) | public/unspecified |
| `/case/{case_id}/attachment` | `GET` | `download_attachment` | `app/main.py` | Attachment retrieval/view endpoint | authenticated |
| `/case/{case_id}/attachment/inline` | `GET` | `view_attachment_inline` | `app/main.py` | Attachment retrieval/view endpoint | authenticated |
| `/case/{case_id}/pdf` | `GET` | `case_pdf` | `app/main.py` | Case PDF generation endpoint | authenticated |
| `/diag/schema` | `GET` | `diagnostic_schema` | `app/main.py` | Diagnostic endpoint to check database schema state. | public/unspecified |
| `/forgot-password` | `GET` | `forgot_password_page` | `app/main.py` | Password reset flow | public/unspecified |
| `/forgot-password` | `POST` | `forgot_password_submit` | `app/main.py` | Password reset flow | public/unspecified |
| `/health` | `GET` | `health_check` | `app/main.py` | Lightweight health check endpoint. | public/unspecified |
| `/healthz` | `GET` | `health_check` | `app/main.py` | Lightweight health check endpoint. | public/unspecified |
| `/intake/{org_id}` | `GET` | `intake_form` | `app/main.py` | Case intake/submission workflow | public/unspecified |
| `/intake/{org_id}` | `POST` | `intake_submit` | `app/main.py` | Case intake/submission workflow | public/unspecified |
| `/irefer/search` | `GET` | `irefer_search` | `app/main.py` | Proxy iRefer guidelines search. Results are cached in memory after first fetch. | radiologist |
| `/login` | `GET` | `login_page` | `app/main.py` | Login/session entry point | public/unspecified |
| `/login` | `POST` | `login_submit` | `app/main.py` | Login/session entry point | public/unspecified |
| `/logout` | `GET` | `logout` | `app/main.py` | Logout and clear session | public/unspecified |
| `/mt` | `GET` | `mt_dashboard` | `app/main.py` | Superuser: Multi-tenant dashboard overview | admin |
| `/mt/create-org` | `GET` | `mt_create_org_page` | `app/main.py` | Superuser: Create new organisation form | admin |
| `/mt/create-org` | `POST` | `mt_create_org_submit` | `app/main.py` | Superuser: Create new organisation | admin |
| `/mt/dashboard` | `GET` | `mt_dashboard` | `app/main.py` | Superuser: Multi-tenant dashboard overview | admin |
| `/mt/org/{org_id}` | `GET` | `mt_org_detail` | `app/main.py` | Superuser: View organisation details | admin |
| `/mt/org/{org_id}/add-user` | `GET` | `mt_add_user_page` | `app/main.py` | Superuser: Add user to organisation form | admin |
| `/mt/org/{org_id}/add-user` | `POST` | `mt_add_user_submit` | `app/main.py` | Superuser: Add user to organisation | admin |
| `/mt/org/{org_id}/edit` | `GET` | `mt_edit_org_page` | `app/main.py` | Superuser: Edit organisation form | admin |
| `/mt/org/{org_id}/edit` | `POST` | `mt_edit_org_submit` | `app/main.py` | Superuser: Update organisation | admin |
| `/mt/org/{org_id}/edit-user/{user_id}` | `GET` | `mt_edit_user_page` | `app/main.py` | Superuser: Edit user form | admin |
| `/mt/org/{org_id}/edit-user/{user_id}` | `POST` | `mt_edit_user_submit` | `app/main.py` | Superuser: Save user changes | admin |
| `/mt/org/{org_id}/remove-user/{user_id}` | `GET` | `mt_remove_user` | `app/main.py` | Superuser: Remove user from organisation | admin |
| `/mt/organisations` | `GET` | `mt_organisations` | `app/main.py` | Superuser: View and manage all organisations | admin |
| `/mt/protocols` | `GET` | `mt_protocols_page` | `app/main.py` | Superuser: Manage protocol templates across all organisations | admin |
| `/mt/protocols/add` | `POST` | `mt_protocols_add` | `app/main.py` | Superuser: Add a new protocol template | admin |
| `/mt/protocols/delete/{protocol_id}` | `POST` | `mt_protocols_delete` | `app/main.py` | Superuser: Delete a protocol template | admin |
| `/mt/protocols/edit/{protocol_id}` | `POST` | `mt_protocols_edit` | `app/main.py` | Superuser: Edit a protocol template | admin |
| `/mt/test` | `GET` | `mt_test` | `app/main.py` | Test page to check multi-tenant database | admin |
| `/mt/users` | `GET` | `mt_users` | `app/main.py` | Superuser: View and manage all superusers (system-level admins) | admin |
| `/radiologist` | `GET` | `radiologist_dashboard` | `app/main.py` | Radiologist review/vetting workflow | radiologist |
| `/reset-password` | `GET` | `reset_password_page` | `app/main.py` | Password reset flow | public/unspecified |
| `/reset-password` | `POST` | `reset_password_submit` | `app/main.py` | Password reset flow | public/unspecified |
| `/robots.txt` | `GET` | `robots_txt` | `app/main.py` | Robots.txt endpoint to prevent search engine indexing. | public/unspecified |
| `/settings` | `GET` | `settings_page` | `app/main.py` | Configuration and master data management | admin |
| `/settings/institution/add` | `POST` | `add_institution` | `app/main.py` | Configuration and master data management | admin |
| `/settings/institution/delete/{inst_id}` | `POST` | `delete_institution_route` | `app/main.py` | Configuration and master data management | admin |
| `/settings/institution/edit/{inst_id}` | `POST` | `edit_institution` | `app/main.py` | Configuration and master data management | admin |
| `/settings/protocol/add` | `POST` | `settings_add_protocol` | `app/main.py` | Configuration and master data management | admin |
| `/settings/protocol/delete` | `POST` | `settings_delete_protocol` | `app/main.py` | Configuration and master data management | admin |
| `/settings/protocol/delete/{protocol_id}` | `POST` | `delete_protocol_route` | `app/main.py` | Configuration and master data management | admin |
| `/settings/protocol/edit/{protocol_id}` | `POST` | `edit_protocol` | `app/main.py` | Configuration and master data management | admin |
| `/settings/radiologist/add` | `POST` | `add_radiologist` | `app/main.py` | Radiologist review/vetting workflow | admin |
| `/settings/radiologist/delete` | `POST` | `remove_radiologist` | `app/main.py` | Radiologist review/vetting workflow | admin |
| `/settings/radiologist/edit/{name}` | `GET` | `edit_radiologist_page` | `app/main.py` | Radiologist review/vetting workflow | admin |
| `/settings/radiologist/update` | `POST` | `update_radiologist` | `app/main.py` | Radiologist review/vetting workflow | admin |
| `/settings/study-descriptions` | `GET` | `study_descriptions_page` | `app/main.py` | Superuser page to manage study description presets for their organization | superuser |
| `/settings/study-descriptions/add` | `POST` | `add_study_description` | `app/main.py` | Add new study description preset for user's organization | superuser |
| `/settings/study-descriptions/delete/{preset_id}` | `POST` | `delete_study_description` | `app/main.py` | Delete study description preset from user's organization | superuser |
| `/settings/study-descriptions/edit/{preset_id}` | `POST` | `edit_study_description` | `app/main.py` | Edit study description preset for user's organization | superuser |
| `/settings/user/access` | `POST` | `update_user_access` | `app/main.py` | Configuration and master data management | admin |
| `/settings/user/add` | `POST` | `add_user` | `app/main.py` | Configuration and master data management | admin |
| `/settings/user/delete` | `POST` | `remove_user` | `app/main.py` | Configuration and master data management | admin |
| `/settings/user/edit` | `POST` | `edit_user` | `app/main.py` | Configuration and master data management | admin |
| `/submit` | `GET` | `submit_form` | `app/main.py` | Case intake/submission workflow | admin |
| `/submit` | `POST` | `submit_case` | `app/main.py` | Case intake/submission workflow | admin |
| `/submit/referral-trial` | `GET` | `referral_trial_form` | `app/main.py` | Case intake/submission workflow | admin |
| `/submit/referral-trial/create` | `POST` | `referral_trial_create` | `app/main.py` | Case intake/submission workflow | admin |
| `/submit/referral-trial/parse` | `POST` | `referral_trial_parse` | `app/main.py` | Case intake/submission workflow | admin |
| `/submitted/{case_id}` | `GET` | `submitted` | `app/main.py` | Case intake/submission workflow | admin |
| `/super/billing` | `GET` | `super_billing_page` | `app/main.py` | Multi-tenant/org management endpoint | superuser |
| `/super/billing.csv` | `GET` | `super_billing_csv` | `app/main.py` | Multi-tenant/org management endpoint | superuser |
| `/super/orgs` | `GET` | `super_orgs_page` | `app/main.py` | Multi-tenant/org management endpoint | superuser |
| `/super/users` | `GET` | `super_users_page` | `app/main.py` | Multi-tenant/org management endpoint | superuser |
| `/vet/{case_id}` | `GET` | `vet_form` | `app/main.py` | Radiologist review/vetting workflow | radiologist |
| `/vet/{case_id}` | `POST` | `vet_submit` | `app/main.py` | Radiologist review/vetting workflow | radiologist |
| `/admin/case/{case_id}` | `GET` | `get_case_detail` | `app/routers/multitenant.py` | Get case detail (with org_id validation). | org_context |
| `/admin/cases` | `GET` | `org_cases` | `app/routers/multitenant.py` | List cases for current organisation. | org_context |
| `/admin/settings/users` | `GET` | `org_admin_users` | `app/routers/multitenant.py` | Org admin: Manage users in their organisation. | org_admin |
| `/admin/settings/users/create` | `POST` | `org_admin_create_user` | `app/routers/multitenant.py` | Org admin: Create new user in their organisation. | org_admin |
| `/login` | `POST` | `login` | `app/routers/multitenant.py` | Login with username/password and set session. | public/unspecified |
| `/logout` | `GET` | `logout` | `app/routers/multitenant.py` | Logout and clear session. | public/unspecified |
| `/select-org` | `GET` | `select_org` | `app/routers/multitenant.py` | Select an organisation to work in. | authenticated |
| `/select-org` | `POST` | `select_org_post` | `app/routers/multitenant.py` | Set selected organisation in session. | authenticated |
| `/superuser/organisations` | `GET` | `superuser_orgs` | `app/routers/multitenant.py` | Superuser view: List all organisations. | superuser |
| `/superuser/organisations/create` | `POST` | `create_org` | `app/routers/multitenant.py` | Superuser: Create new organisation. | superuser |
| `/superuser/organisations/{org_id}/members` | `GET` | `superuser_org_members` | `app/routers/multitenant.py` | Superuser: Manage members of an organisation. | superuser |
| `/superuser/organisations/{org_id}/members/add` | `POST` | `superuser_add_member` | `app/routers/multitenant.py` | Superuser: Add existing user to organisation. | superuser |
