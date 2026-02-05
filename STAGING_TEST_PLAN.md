# Staging Environment Test Plan - Vetting App V2

## Overview
This document outlines a comprehensive test plan for validating all 10 bug fixes in a staging environment before production deployment.

---

## Pre-Deployment Setup

### 1. Environment Preparation

```powershell
# Create staging directory structure
$stagingPath = "C:\Staging\VettingApp_V2_$(Get-Date -Format 'yyyyMMdd')"
New-Item -ItemType Directory -Path $stagingPath -Force

# Copy production code to staging
Copy-Item "C:\Users\pmend\project\Vetting app\*" $stagingPath -Recurse -Force

# Backup production database
Copy-Item "C:\Users\pmend\project\Vetting app\hub.db" `
    "C:\Backups\hub.db.production.$(Get-Date -Format 'yyyyMMdd_HHmmss').backup" -Force

# Copy database to staging (fresh or copy for testing)
Copy-Item "C:\Users\pmend\project\Vetting app\hub.db" "$stagingPath\hub.db" -Force
```

### 2. Staging Server Configuration
- Use separate port: 8001 (vs production 8000)
- Use separate database or database backup
- Enable verbose logging
- Configure monitoring/alerting

---

## Test Execution Plan

### Phase 1: Smoke Tests (Basic Functionality)
**Duration: 15 minutes**
**Tester: QA Lead**

| Test | Steps | Expected Result | Status |
|------|-------|-----------------|--------|
| App Startup | Start staging application | No errors in logs | ☐ PASS |
| Database Migration | Check logs for migration | modified_at column created | ☐ PASS |
| Login | Admin login with admin/admin123 | Dashboard loads | ☐ PASS |
| Navigation | Click through main pages | All pages load without errors | ☐ PASS |

### Phase 2: Bug Fix Validation Tests
**Duration: 45 minutes**
**Tester: QA Team**

#### Bug 1: User Creation without Radiologist Profile
**Test ID:** BUG1-TC01
```
Steps:
1. Navigate to Settings > Users tab
2. Click "Add New User"
3. Fill form:
   - Username: test_admin_user
   - Password: TempPassword123!
   - First Name: Test
   - Surname: Admin
   - Email: test@example.com
   - Role: Admin (NOT radiologist)
   - Leave "Link to Radiologist" blank
4. Click "Add User"

Expected Result:
✓ User created successfully
✓ No error about radiologist profile
✓ User appears in Current Users list with Admin role
✓ radiologist_name field is NULL in database

Acceptance Criteria:
- Admin users can be created without radiologist profile
- System doesn't enforce radiologist_name for admin role
```

#### Bug 2: Institution Timestamps
**Test ID:** BUG2-TC01
```
Steps:
1. Navigate to Settings > Institutions tab
2. Create new institution:
   - Name: Test Hospital V2
   - SLA: 48 hours
3. Click "Add Institution"
4. Verify in Current Institutions table:
   - Created column shows timestamp (DD-MM-YYYY HH:MM format)
   - Modified column shows timestamp

Expected Result:
✓ Both Created and Modified columns displayed
✓ Timestamps in DD-MM-YYYY HH:MM format
✓ Both show same time (since just created)

Acceptance Criteria:
- Institution timestamps are properly formatted
- Modified column exists and displays
```

**Test ID:** BUG2-TC02
```
Steps:
1. Find "Test Hospital V2" in Current Institutions
2. Click "Edit" button
3. Change SLA to 72 hours
4. Click save
5. Navigate back to Institutions tab
6. Verify Modified timestamp changed

Expected Result:
✓ Modified timestamp updated to current time
✓ Created timestamp remains unchanged
✓ Time difference visible between Created and Modified

Acceptance Criteria:
- Modified timestamp updates on edit
- Created timestamp immutable
- Both timestamps properly formatted
```

#### Bug 3: Column Sorting
**Test ID:** BUG3-TC01
```
Steps:
1. Navigate to Admin Dashboard
2. Locate column headers: Study, Radiologist
3. Click "Study" column header
4. Verify:
   - Arrow indicator appears (↑ or ↓)
   - Cases reorder by study description
5. Click "Study" again
6. Verify order reverses

Expected Result:
✓ Sort arrow appears next to Study
✓ Cases sort alphabetically by study_description
✓ Clicking again reverses sort direction
✓ URL updates with sort_by=study_description

Acceptance Criteria:
- Study column is sortable with visual indicator
- Sort direction toggles properly
```

**Test ID:** BUG3-TC02
```
Steps:
1. Click "Radiologist" column header
2. Verify:
   - Arrow indicator appears
   - Cases reorder by radiologist name
3. Click again to reverse order

Expected Result:
✓ Sort arrow appears next to Radiologist
✓ Cases sort by radiologist name
✓ Sort direction toggles properly

Acceptance Criteria:
- Radiologist column is sortable with visual indicator
```

#### Bug 4: Edit Case Form Readability
**Test ID:** BUG4-TC01
```
Steps:
1. Navigate to Admin Dashboard
2. Click a case "Open" link
3. Click "Edit Case" button
4. Evaluate form readability:
   - Can you clearly see form labels?
   - Can you read text in input fields?
   - Is contrast good when typing?
   - Does focus state (blue border) show clearly?

Expected Result:
✓ Labels clearly visible (white text on dark)
✓ Input text clearly readable (white text on dark blue)
✓ Good contrast throughout
✓ Focus state has visible blue border + shadow
✓ No white-on-white or light-on-light issues

Acceptance Criteria:
- All form elements have adequate contrast
- Text is legible when typing
- Focus states are clearly visible
```

#### Bug 5: Radiologist Vetting - No Download
**Test ID:** BUG5-TC01
```
Prerequisites:
- Have a case with an attachment assigned to radiologist
- Case status: pending

Steps:
1. Login as radiologist user
2. Navigate to Radiologist Dashboard
3. Open a pending case with attachment
4. Look at "Attachment" section

Expected Result:
✓ Attachment filename shown
✓ NO "Download" link visible
✓ NO "Download" button visible
✓ Attachment preview visible in right panel
✓ Can view attachment in embedded preview only

Acceptance Criteria:
- Download option completely removed
- Radiologist can only view via preview
- No HTML/CSS remnants of download link
```

#### Bug 6 & 7: Protocol Requirement on Reject
**Test ID:** BUG6-TC01
```
Prerequisites:
- Case assigned to radiologist
- Case status: pending
- With protocols defined

Steps:
1. Login as radiologist
2. Open pending case
3. In "Vetting Decision" form:
   - Select "Reject" from Decision dropdown
4. Observe Protocol field

Expected Result:
✓ Protocol field becomes HIDDEN
✓ Protocol field not required
✓ Comment field appears and is REQUIRED
✓ Info box shows: "⚠️ Required: Comment is mandatory when rejecting a case"

Acceptance Criteria:
- Protocol field hidden for Reject
- Comment field mandatory for Reject
- User cannot submit without comment
```

**Test ID:** BUG6-TC02
```
Steps (continue from BUG6-TC01):
1. Try to submit form without comment
2. Observe error

Expected Result:
✓ Form validation prevents submission
✓ Error message: "Comment is required when rejecting a case"
✓ Focus moves to comment field

Acceptance Criteria:
- Backend validates comment is required for reject
```

**Test ID:** BUG6-TC03
```
Steps:
1. Select "Approve" from Decision dropdown
2. Observe Protocol field

Expected Result:
✓ Protocol field becomes VISIBLE
✓ Protocol field is REQUIRED
✓ Comment field optional
✓ Cannot submit without selecting protocol

Acceptance Criteria:
- Protocol field visible for Approve
- Protocol field mandatory for Approve
- Validation prevents empty protocol
```

#### Bug 8: PDF Generation
**Test ID:** BUG8-TC01
```
Prerequisites:
- Have a vetted case (status=vetted, decision=Approve)

Steps:
1. Navigate to Admin Dashboard
2. Find vetted case
3. Click case to view details
4. Click "Open vetting Form" (PDF link)
5. Wait for PDF to generate and download
6. Verify PDF content

Expected Result:
✓ PDF downloads without error
✓ No error message in logs
✓ PDF contains case details:
  - Case ID
  - Created timestamp
  - Patient name
  - Radiologist
  - Vetting decision
  - Protocol
✓ Timestamps formatted correctly (DD-MM-YYYY HH:MM)

Acceptance Criteria:
- PDF generates without 'sqlite3.Row' error
- All case data present in PDF
- PDF is readable and properly formatted
```

**Test ID:** BUG8-TC02
```
Prerequisites:
- Have a rejected case (status=rejected, decision=Reject)

Steps:
1. Navigate to Admin Dashboard
2. Find rejected case
3. Click "Open vetting Form"
4. Verify PDF generates correctly

Expected Result:
✓ PDF generates without error
✓ Decision shows "Reject"
✓ Protocol field omitted (since rejected)
✓ Comment displayed if provided

Acceptance Criteria:
- PDF generation works for rejected cases
- Protocol not shown for rejected decisions
```

#### Bug 9: Prevent Editing Approved Cases
**Test ID:** BUG9-TC01
```
Prerequisites:
- Have an approved case (status=vetted, decision=Approve)

Steps:
1. Navigate to Admin Dashboard
2. Click on approved case
3. Observe Edit button

Expected Result:
✓ "Edit Case" button is NOT visible
✓ No Edit button displayed
✓ Only "Back" and "Logout" buttons shown

Acceptance Criteria:
- Edit button hidden for approved cases
```

**Test ID:** BUG9-TC02
```
Prerequisites:
- Have a pending case (status=pending)

Steps:
1. Navigate to Admin Dashboard
2. Click on pending case
3. Observe Edit button

Expected Result:
✓ "Edit Case" button IS visible
✓ Can click button without restriction
✓ Edit form loads

Acceptance Criteria:
- Edit button visible for non-approved cases
```

**Test ID:** BUG9-TC03
```
Steps:
1. Try to manually navigate to approved case edit URL:
   URL: /admin/case/{approved_case_id}/edit
2. Observe response

Expected Result:
✓ Returns 403 Forbidden error
✓ Error message: "Cannot edit approved cases"
✓ Redirected to case details or home

Acceptance Criteria:
- Backend prevents access to edit endpoint
- Security enforced even if button bypassed
```

#### Bug 10: Updated Labels
**Test ID:** BUG10-TC01
```
Prerequisites:
- Case with attachment

Steps:
1. Navigate to case details page
2. Look at the attachment links

Expected Result:
✓ Link text reads "Download referral" (not "Download attachments")
✓ Link text reads "Open vetting Form" (not "Open PDF")

Acceptance Criteria:
- Labels updated as specified
- User-friendly terminology used
```

### Phase 3: Integration Tests
**Duration: 30 minutes**
**Tester: QA Team**

| Scenario | Test Steps | Expected Result | Status |
|----------|-----------|-----------------|--------|
| User Workflow | Create user → Create case → Assign radiologist → Vet case → Review PDF | All steps work without errors | ☐ PASS |
| Concurrent Users | Multiple users on dashboard simultaneously | No database locks or conflicts | ☐ PASS |
| Data Integrity | Reject case → Try to edit → Approve case → Try to edit | State transitions work correctly | ☐ PASS |
| Performance | Load dashboard with 100+ cases | Loads in <3 seconds | ☐ PASS |

### Phase 4: Regression Tests
**Duration: 30 minutes**
**Tester: QA Lead**

| Feature | Test | Expected Result | Status |
|---------|------|-----------------|--------|
| Login | Login with valid credentials | Dashboard loads | ☐ PASS |
| Submission | Submit new case | Case created, status=pending | ☐ PASS |
| Settings | Manage institutions/radiologists/users | CRUD operations work | ☐ PASS |
| CSV Export | Export cases to CSV | File generated correctly | ☐ PASS |
| Filtering | Filter cases by institution/radiologist | Results accurate | ☐ PASS |

---

## Test Execution Tracking

### Test Summary Template
```
Date: __________
Tester: __________
Environment: Staging
Build Version: V2

Total Tests Planned: 15
Tests Passed: ____
Tests Failed: ____
Tests Blocked: ____

Issues Found:
1. [Description] - Severity: [Critical/High/Medium/Low]
2. [Description] - Severity: [Critical/High/Medium/Low]

Blockers for Production:
- [ ] None
- [ ] Yes, see issue #_

Recommendation:
[ ] Ready for Production
[ ] Needs Fixes (issues listed above)
[ ] Not Ready
```

---

## Defect Severity Guidelines

| Severity | Definition | Example |
|----------|-----------|---------|
| **Critical** | Application crash or data loss | PDF generation error with every case |
| **High** | Major feature broken | Can't reject cases |
| **Medium** | Feature works but has issues | Sort direction doesn't toggle |
| **Low** | Minor UI/UX issue | Label text slightly off |

---

## Sign-Off

- [ ] QA Lead: _________________ Date: _________
- [ ] Tech Lead: ________________ Date: _________
- [ ] Product Manager: __________ Date: _________

**Production Deployment Approved:** YES / NO
