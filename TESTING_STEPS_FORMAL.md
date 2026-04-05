# Formal Testing Steps

## Document Information

- Release: current RadFlow build
- Deployment Date: [to be filled]
- Tested By: [to be filled]
- Approved By: [to be filled]
- Environment: staging or production

## Prerequisites

- target application is running
- a database backup exists for the environment being tested
- you have at least one owner, one admin, and one practitioner test account
- SMTP is configured if password-reset or notification email testing is in scope

## Core Execution Order

1. Application availability
2. Authentication and MFA
3. Owner workflow
4. Admin dashboard and reporting
5. Submission and vetting flow
6. Settings and master data
7. Attachments and PDFs

## 1. Application Availability

STEP 1.1
Open the target application URL.

Expected:

- landing page or login page loads without server error

Result: [ ] PASS  [ ] FAIL
Notes: _________________________________

## 2. Authentication And MFA

STEP 2.1
Sign in as owner/superuser.

Expected:

- redirect to `/owner`

Result: [ ] PASS  [ ] FAIL

STEP 2.2
Sign out and sign in as organisation admin.

Expected:

- redirect to `/admin`

Result: [ ] PASS  [ ] FAIL

STEP 2.3
Sign out and sign in as practitioner.

Expected:

- redirect to `/radiologist`

Result: [ ] PASS  [ ] FAIL

STEP 2.4
Test an MFA-enabled account.

Expected:

- login redirects to `/login/mfa`
- MFA code completes sign-in successfully

Result: [ ] PASS  [ ] FAIL

STEP 2.5
If available, test an admin-capable account marked `mfa_required` but not enrolled.

Expected:

- user is redirected to `/account?msg=mfa_required`

Result: [ ] PASS  [ ] FAIL

STEP 2.6
If SMTP is configured, test forgot-password and reset-password.

Expected:

- password reset request succeeds
- reset link flow updates the password

Result: [ ] PASS  [ ] FAIL

## 3. Owner Workflow

STEP 3.1
Open `/owner`.

Expected:

- owner dashboard loads

Result: [ ] PASS  [ ] FAIL

STEP 3.2
Create or edit an organisation.

Expected:

- save succeeds

Result: [ ] PASS  [ ] FAIL

STEP 3.3
Add or edit an organisation user.

Expected:

- user save succeeds
- role selection behaves correctly

Result: [ ] PASS  [ ] FAIL

STEP 3.4
Set or clear MFA-required for an organisation user where appropriate.

Expected:

- MFA-required state persists after save

Result: [ ] PASS  [ ] FAIL

## 4. Admin Dashboard And Reporting

STEP 4.1
Open `/admin`.

Expected:

- dashboard loads with worklist and metrics

Result: [ ] PASS  [ ] FAIL

STEP 4.2
Apply dashboard filters for date range, institution, and practitioner.

Expected:

- dashboard and worklist update consistently

Result: [ ] PASS  [ ] FAIL

STEP 4.3
Export `/admin.csv`.

Expected:

- CSV downloads successfully

Result: [ ] PASS  [ ] FAIL

STEP 4.4
Export `/admin.events.csv`.

Expected:

- event CSV downloads successfully

Result: [ ] PASS  [ ] FAIL

STEP 4.5
Export `/admin/dashboard-report.pdf`.

Expected:

- dashboard PDF downloads successfully

Result: [ ] PASS  [ ] FAIL

## 5. Submission And Vetting Flow

STEP 5.1
Create a case through `/submit` or `/intake/{org_id}`.

Expected:

- case is created successfully

Result: [ ] PASS  [ ] FAIL

STEP 5.2
Assign the case to a practitioner from admin workflow.

Expected:

- assignment persists

Result: [ ] PASS  [ ] FAIL

STEP 5.3
Sign in as practitioner and open `/vet/{case_id}`.

Expected:

- vetting page loads

Result: [ ] PASS  [ ] FAIL

STEP 5.4
Submit a practitioner decision.

Expected:

- case status updates
- decision is reflected back in admin reporting

Result: [ ] PASS  [ ] FAIL

STEP 5.5
If applicable, reopen the case from admin workflow.

Expected:

- reopened state is visible and usable

Result: [ ] PASS  [ ] FAIL

## 6. Settings And Master Data

STEP 6.1
Open `/settings`.

Expected:

- settings page loads

Result: [ ] PASS  [ ] FAIL

STEP 6.2
Test institutions, protocols, and practitioner profiles.

Expected:

- CRUD actions succeed

Result: [ ] PASS  [ ] FAIL

STEP 6.3
Test organisation user management.

Expected:

- add/edit/delete/access actions succeed

Result: [ ] PASS  [ ] FAIL

STEP 6.4
Update report header/footer text.

Expected:

- settings save successfully

Result: [ ] PASS  [ ] FAIL

STEP 6.5
Test study description preset add/edit/archive/restore.

Expected:

- preset actions succeed

Result: [ ] PASS  [ ] FAIL

## 7. Attachments And PDFs

STEP 7.1
Open case attachment download, inline view, and preview routes.

Expected:

- file access behaves correctly for authorised user

Result: [ ] PASS  [ ] FAIL

STEP 7.2
Open `/case/{case_id}/pdf`.

Expected:

- case PDF downloads successfully

Result: [ ] PASS  [ ] FAIL

## Final Validation

Overall Result:

- [ ] Ready for promotion or release
- [ ] Minor issues only
- [ ] Major issues found
- [ ] Block release

Issues Found:

1. ___________________________________
2. ___________________________________
3. ___________________________________

Approvals:

- [ ] Product Manager Approved
- [ ] Tech Lead Approved
- [ ] QA Approved
