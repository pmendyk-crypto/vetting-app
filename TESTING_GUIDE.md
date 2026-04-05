# Testing Guide

## Purpose

This guide reflects the current testable workflow in the repo.

The codebase currently supports local manual testing well through tracked PowerShell scripts. It does not currently provide a single first-class automated test command in repo scripts.

## Recommended Test Sequence

1. Run the app locally on the normal env file.
2. Repeat validation on the isolated local test environment.
3. Push `develop`.
4. Validate staging.
5. Promote to `main` only after staging passes.

## Local Manual Test Environment

### Primary local run

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.local.example .env.local
.\scripts\run-local.ps1 -Reload
```

Primary URL:

- `http://127.0.0.1:8000`

### Isolated local test run

```powershell
.\scripts\setup-test-env.ps1
.\scripts\run-test-local.ps1
```

Isolated URL:

- `http://127.0.0.1:8001`

This path uses:

- `.env.test.local`
- `hub.test.db`
- `uploads-test`

## Current High-Value Smoke Tests

### Authentication and MFA

- sign in through `/login`
- verify MFA redirect to `/login/mfa` for MFA-enabled users
- verify required-but-not-enrolled admin users are redirected to `/account?msg=mfa_required`
- verify `/account` can begin, enable, and disable MFA
- verify password reset request and reset flow if SMTP is configured

### Owner workflow

- sign in as superuser and confirm redirect to `/owner`
- create or edit an organisation
- add or edit an organisation user
- confirm MFA-required flags can be set for the initial admin or managed users
- test owner password reset action for an organisation user

### Admin workflow

- open `/admin`
- filter dashboard by date range, institution, and practitioner
- export:
  - `/admin.csv`
  - `/admin.events.csv`
  - `/admin/dashboard-report.pdf`
- open a case, edit it, reassign it, and reopen it where applicable
- send a practitioner notification from `/admin/notify-radiologist`

### Practitioner workflow

- sign in as practitioner and confirm redirect to `/radiologist`
- open `/vet/{case_id}`
- verify decision submission and comment handling
- verify the updated decision appears back in admin reporting

### Settings and presets

- institutions CRUD
- practitioner profile CRUD
- protocols CRUD
- user add/edit/delete/access toggle
- report header/footer updates through settings
- study description preset add/edit/archive/restore

### Submission and attachments

- create a case through `/submit`
- create a case through `/intake/{org_id}` if using public intake
- test referral parser trial on `/submit/referral-trial`
- verify attachment download, inline view, preview, and case PDF output

## Current Testing Reality

Verified from repo state:

- no tracked `pytest` dependency in `requirements.txt`
- there are ad hoc test scripts in the repo and `tests/` folder
- the most dependable documented path today is manual browser-based verification against the normal and isolated local environments

## Staging Gate

Before promoting to `main`, confirm on staging:

- owner login
- admin login
- practitioner login
- MFA verification path
- password reset flow if SMTP is enabled there
- dashboard exports
- one full submit -> assign -> vet -> report loop
