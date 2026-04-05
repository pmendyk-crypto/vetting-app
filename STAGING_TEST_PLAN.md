# Staging Environment Test Plan

## Overview

This document outlines the current staging validation plan before promoting `develop` to `main`.

## Pre-Deployment Setup

### 1. Deployment Trigger

```powershell
git push origin develop
```

### 2. Staging Configuration

- staging is deployed by `.github/workflows/deploy-staging.yml`
- target Azure Web App: `lumosradflow-staging`
- confirm staging app settings are present for auth, storage, reporting, and SMTP-sensitive flows when needed

## Test Execution Plan

### Phase 1: Smoke Tests

Duration: 15 minutes
Tester: QA Lead

| Test | Steps | Expected Result | Status |
|------|-------|-----------------|--------|
| App Startup | Open staging URL | App loads without server error | [ ] PASS |
| Owner Login | Sign in as owner/superuser | Redirects to `/owner` | [ ] PASS |
| Admin Login | Sign in as admin | Redirects to `/admin` | [ ] PASS |
| Practitioner Login | Sign in as practitioner | Redirects to `/radiologist` | [ ] PASS |
| MFA Login | Test MFA-enabled account | Redirects through `/login/mfa` and completes sign-in | [ ] PASS |

### Phase 2: Core Workflow Validation

Duration: 45 minutes
Tester: QA Team

#### Test 1: Owner organisation management

Test ID: `STAGE-TC01`

Steps:

1. Open `/owner`
2. Create or edit a staging organisation
3. Add or edit an organisation user
4. Set MFA-required where appropriate

Expected result:

- organisation page loads
- user management actions succeed
- MFA-required flag persists

#### Test 2: Admin dashboard and reporting

Test ID: `STAGE-TC02`

Steps:

1. Open `/admin`
2. Apply dashboard filters
3. Export `/admin.csv`
4. Export `/admin.events.csv`
5. Export `/admin/dashboard-report.pdf`

Expected result:

- dashboard loads
- filters update results
- all exports download successfully

#### Test 3: Settings

Test ID: `STAGE-TC03`

Steps:

1. Open `/settings`
2. Verify institutions, protocols, users, and study description presets
3. Save report header/footer text

Expected result:

- CRUD actions succeed
- report text saves
- updated report text appears in generated report output where expected

#### Test 4: Submission and vetting

Test ID: `STAGE-TC04`

Steps:

1. Create a case via `/submit` or `/intake/{org_id}`
2. Assign a practitioner
3. Sign in as practitioner
4. Vet the case
5. Re-open or review the case from admin

Expected result:

- case moves through the expected lifecycle
- practitioner action is reflected in admin view
- exports include the updated state

#### Test 5: Authentication edge cases

Test ID: `STAGE-TC05`

Steps:

1. Test invalid login
2. Test MFA-enabled login
3. Test MFA-required but not enrolled admin login
4. Test forgot-password and reset-password if SMTP is configured

Expected result:

- invalid login is rejected
- MFA flow completes
- MFA-required user is sent to `/account`
- password reset behaves correctly for the environment configuration

### Phase 3: Regression Checks

Duration: 30 minutes
Tester: QA Team

| Scenario | Test Steps | Expected Result | Status |
|----------|-----------|-----------------|--------|
| Login | Owner, admin, and practitioner logins all work | Correct landing pages | [ ] PASS |
| Submission | Submit new case | Case created and visible | [ ] PASS |
| Settings | Manage institutions, protocols, users, presets | CRUD operations work | [ ] PASS |
| Exports | CSV and PDF exports | Files generate correctly | [ ] PASS |
| Notifications | Practitioner notify flow | Email path works when configured | [ ] PASS |

## Test Execution Tracking

Date: __________
Tester: __________
Environment: Staging
Branch: `develop`

Issues Found:

1. ___________________________________
2. ___________________________________

Recommendation:

- [ ] Ready for promotion to `main`
- [ ] Needs fixes before promotion
- [ ] Not ready

## Severity Guidelines

| Severity | Definition | Example |
|----------|-----------|---------|
| Critical | Application crash or data loss | Staging cannot start or sign-in fails for all users |
| High | Major workflow broken | Admin or practitioner flow cannot complete |
| Medium | Feature works but has issues | Export succeeds but formatting/content is wrong |
| Low | Minor UI/UX issue | Small wording or presentation issue |
