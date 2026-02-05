# Formal Testing Steps - Vetting App V2 Production Deployment

## Document Information
- **Release**: Vetting App V2
- **Deployment Date**: [To be filled]
- **Tested By**: [To be filled]
- **Approved By**: [To be filled]
- **Environment**: Production

---

## Quick Start Testing (15 minutes)

### Prerequisites
- [ ] Production application is running
- [ ] Database backup created
- [ ] You have admin login credentials
- [ ] You have radiologist test account credentials

### Test Execution

#### 1. Application Availability
```
STEP 1.1: Open browser and navigate to application URL
URL: [Your production URL]
Expected: Login page loads within 5 seconds

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________
```

#### 2. Admin Login & Dashboard
```
STEP 2.1: Login with admin credentials
Username: admin
Password: [your password]

STEP 2.2: Wait for dashboard to load
Expected: Dashboard displays with case summary

STEP 2.3: Verify dashboard elements visible
- [ ] Status tabs (All, Pending, Vetted, Rejected)
- [ ] Filter section (Institution, Radiologist, Search)
- [ ] Case table with columns
- [ ] Sort indicators on column headers

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________
```

#### 3. Column Sorting (Bug 3)
```
STEP 3.1: Click "Study" column header
Expected: 
  - Arrow indicator appears (↓)
  - Cases reorder by study description

STEP 3.2: Click "Study" header again
Expected: Arrow changes direction (↑), cases reverse order

STEP 3.3: Click "Radiologist" column header
Expected:
  - Arrow appears next to Radiologist
  - Cases reorder by radiologist name

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________
```

---

## Standard Testing (30 minutes)

### Bug 1: User Creation

**Objective**: Verify admin users can be created without radiologist profile

```
TEST CASE: BUG1-001
Severity: HIGH
Precondition: Logged in as admin

STEP 1: Navigate to Settings → Users tab
Expected: Users management page loads
Result: [ ] PASS  [ ] FAIL

STEP 2: Click "Add New User" section
Expected: Form displayed with fields:
  - Username
  - Password
  - First Name
  - Surname
  - Email
  - Role (dropdown)
  - Link to Radiologist (text field)
Result: [ ] PASS  [ ] FAIL

STEP 3: Fill in the form for ADMIN user:
Field Data:
  Username: qa_test_admin_001
  Password: TestPass123!@
  First Name: QA
  Surname: TestAdmin
  Email: qa@test.local
  Role: Admin
  Link to Radiologist: [LEAVE BLANK]

STEP 4: Click "Add User" button
Expected: 
  - No error message
  - Form clears
  - Success feedback shown

Result: [ ] PASS  [ ] FAIL
Error message: _________________________

STEP 5: Verify user appears in "Current Users" list
Expected: qa_test_admin_001 listed with:
  - Username: qa_test_admin_001
  - Name: QA TestAdmin
  - Email: qa@test.local
  - Role: ADMIN

Result: [ ] PASS  [ ] FAIL
Notes: _________________________________

CLEANUP: Delete test user after verification
```

---

### Bug 2: Institution Timestamps

**Objective**: Verify institution timestamps are created and modified

```
TEST CASE: BUG2-001 - CREATE WITH TIMESTAMPS
Severity: MEDIUM
Precondition: Logged in as admin

STEP 1: Navigate to Settings → Institutions tab
Expected: Institutions management page loads
Result: [ ] PASS  [ ] FAIL

STEP 2: Create new institution:
Field Data:
  Name: QA Test Hospital 001
  SLA Hours: 48

STEP 3: Click "Add Institution"
Expected: 
  - Form clears
  - No error message
  - Institution appears in list

Result: [ ] PASS  [ ] FAIL

STEP 4: Verify timestamps in "Current Institutions" table
Expected columns visible:
  - [ ] Institution Name
  - [ ] SLA (hours)
  - [ ] Created
  - [ ] Modified
  - [ ] Actions

Result: [ ] PASS  [ ] FAIL

STEP 5: Check timestamp values
Expected:
  - Created shows: DD-MM-YYYY HH:MM format (e.g., 31-01-2026 14:30)
  - Modified shows: Same as Created (just created)
  - Timestamps are today's date and current time

Created timestamp: __________________
Modified timestamp: __________________
Result: [ ] PASS  [ ] FAIL

CLEANUP: Record timestamps for next test
```

```
TEST CASE: BUG2-002 - MODIFIED TIMESTAMP UPDATE
Severity: MEDIUM
Precondition: QA Test Hospital 001 created in BUG2-001

STEP 1: Find "QA Test Hospital 001" in institutions table
Expected: Institution found
Result: [ ] PASS  [ ] FAIL

STEP 2: Click "Edit" button for this institution
Expected: Edit modal/form appears
Result: [ ] PASS  [ ] FAIL

STEP 3: Change SLA from 48 to 72 hours
Expected: SLA field updates
Result: [ ] PASS  [ ] FAIL

STEP 4: Wait 5 seconds, then click save
Expected:
  - Form closes
  - Modal disappears
  - No error message

Result: [ ] PASS  [ ] FAIL

STEP 5: Verify timestamps updated
Expected:
  - Created timestamp: UNCHANGED (same as before)
  - Modified timestamp: CHANGED (newer time)
  - Time difference clearly visible

Created timestamp (should be same): ____________________
Modified timestamp (should be newer): ____________________
Difference: _________________ minutes/seconds

Result: [ ] PASS  [ ] FAIL
Notes: _________________________________

CLEANUP: Delete test institution after verification
```

---

### Bug 4: Edit Case Form Readability

**Objective**: Verify form fields are readable and usable

```
TEST CASE: BUG4-001 - FORM READABILITY
Severity: HIGH
Precondition: Have a pending case in system

STEP 1: Navigate to Admin Dashboard
Expected: Dashboard displays cases
Result: [ ] PASS  [ ] FAIL

STEP 2: Click on a pending case (status = "Pending")
Expected: Case details page loads
Result: [ ] PASS  [ ] FAIL

STEP 3: Click "Edit Case" button
Expected: Edit form loads
Result: [ ] PASS  [ ] FAIL

STEP 4: Evaluate LABEL readability
Visibility Checklist:
  - [ ] "First Name" label clearly visible (white on dark)
  - [ ] "Surname" label clearly visible
  - [ ] "Patient Referral ID" label clearly visible
  - [ ] "Institution" label clearly visible
  - [ ] "Study Description" label clearly visible
  - [ ] "Admin Notes" label clearly visible
  
Overall: [ ] PASS - All labels readable  [ ] FAIL - Some hard to read

Result: [ ] PASS  [ ] FAIL
Notes: _________________________________

STEP 5: Evaluate INPUT FIELD readability
Type in each field and verify visibility:

Field 1 - First Name:
  - Type: "John"
  - Expected: White text clearly visible on dark blue background
  - Readability: [ ] PASS  [ ] FAIL

Field 2 - Surname:
  - Type: "Smith"
  - Expected: Text clearly visible while typing
  - Readability: [ ] PASS  [ ] FAIL

Field 3 - Study Description:
  - Type: "Chest X-Ray"
  - Expected: Text clearly visible in textarea
  - Readability: [ ] PASS  [ ] FAIL

Overall input readability: [ ] PASS  [ ] FAIL

STEP 6: Test FOCUS STATE
Click on each input field and verify:
  - Expected: Blue border appears around field
  - Expected: Background slightly brightens
  - Expected: Cursor clearly visible

Focus state visibility: [ ] PASS  [ ] FAIL
Shadow/glow effect visible: [ ] YES  [ ] NO
Blue border color visible: [ ] YES  [ ] NO

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________

CLEANUP: Click Cancel to exit without saving
```

---

### Bug 5: No Download in Radiologist View

**Objective**: Verify radiologists cannot download attachments

```
TEST CASE: BUG5-001 - NO DOWNLOAD OPTION
Severity: MEDIUM
Precondition: Have pending case with attachment assigned to radiologist

STEP 1: Logout from admin account
Result: [ ] PASS  [ ] FAIL

STEP 2: Login as radiologist
Username: [radiologist account]
Password: [password]
Expected: Radiologist dashboard loads
Result: [ ] PASS  [ ] FAIL

STEP 3: Open a pending case with attachment
Expected: Case vetting page loads
Result: [ ] PASS  [ ] FAIL

STEP 4: Look for attachment section
Expected: Attachment filename displayed
Result: [ ] PASS  [ ] FAIL

STEP 5: Check for download links
Expected:
  - [ ] NO "Download" link present
  - [ ] NO "Download Attachment" link present
  - [ ] NO download button visible
  - [ ] Filename shown without download option
  - [ ] View attachment visible in right preview panel

Download option visibility: 
  - [ ] PASS - No download option
  - [ ] FAIL - Download option found

STEP 6: Verify attachment can be viewed
Expected: 
  - Right panel shows attachment preview (iframe)
  - Attachment is readable in preview
  - No download occurs on page load

Preview functionality: [ ] PASS  [ ] FAIL
Embedded preview working: [ ] YES  [ ] NO

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________

CLEANUP: Logout radiologist account
```

---

### Bug 6 & 7: Protocol on Reject

**Objective**: Verify protocol field hidden when rejecting, shown for approve

```
TEST CASE: BUG6-BUG7-001 - REJECT WORKFLOW
Severity: CRITICAL
Precondition: Logged in as radiologist, have pending case

STEP 1: Open pending case vetting form
Expected: Form loads with Decision dropdown
Result: [ ] PASS  [ ] FAIL

STEP 2: Select "Reject" from Decision dropdown
Expected:
  - Protocol field DISAPPEARS (hidden)
  - Comment field APPEARS and is highlighted as required
  - Red asterisk (*) appears on Comment label
  - Info box shows: "⚠️ Required: Comment is mandatory when rejecting a case"

Visual feedback check:
  - [ ] Protocol field hidden
  - [ ] Comment field visible
  - [ ] Required indicator present
  - [ ] Info box displayed

Result: [ ] PASS  [ ] FAIL

STEP 3: Try to submit without comment
Expected:
  - Form validation prevents submission
  - Error message shown: "Comment is required when rejecting a case"
  - Focus moves to comment field
  - Comment field highlighted in red

Validation check:
  - [ ] Cannot submit without comment
  - [ ] Error message displayed
  - [ ] User guidance provided

Result: [ ] PASS  [ ] FAIL

STEP 4: Enter comment text
Text: "Case needs additional review from radiologist manager"
Expected: Comment field accepts text
Result: [ ] PASS  [ ] FAIL

STEP 5: Click "Save Decision"
Expected:
  - Form submits
  - Page redirects to radiologist dashboard
  - Case status changed to "rejected"
  - No error message

Submission result: [ ] PASS  [ ] FAIL

CLEANUP: Continue to next test case
```

```
TEST CASE: BUG6-BUG7-002 - APPROVE WITH PROTOCOL
Severity: CRITICAL
Precondition: Logged in as radiologist, have pending case (different from BUG6-BUG7-001)

STEP 1: Open pending case vetting form
Expected: Form loads with Decision dropdown
Result: [ ] PASS  [ ] FAIL

STEP 2: Select "Approve" from Decision dropdown
Expected:
  - Protocol field APPEARS (visible)
  - Protocol field shows REQUIRED indicator (*)
  - Comment field is optional
  - Protocol dropdown lists available protocols

Visibility check:
  - [ ] Protocol field visible
  - [ ] Required indicator present
  - [ ] Protocols listed in dropdown

Result: [ ] PASS  [ ] FAIL

STEP 3: Try to submit without selecting protocol
Expected:
  - Form validation prevents submission
  - Error message: "Protocol is required for approved cases"
  - Focus moves to protocol field

Validation: [ ] PASS  [ ] FAIL

STEP 4: Select a protocol from dropdown
Expected: Protocol selected and displayed
Result: [ ] PASS  [ ] FAIL

STEP 5: Click "Save Decision"
Expected:
  - Form submits
  - Page redirects to radiologist dashboard
  - Case status changed to "vetted"
  - Case decision set to "Approve"

Submission result: [ ] PASS  [ ] FAIL

CLEANUP: Verify in admin dashboard that case is approved
```

---

### Bug 8: PDF Generation

**Objective**: Verify PDF generation works without errors

```
TEST CASE: BUG8-001 - PDF APPROVED CASE
Severity: CRITICAL
Precondition: Have an approved case (status=vetted, decision=Approve)

STEP 1: Login as admin
Result: [ ] PASS  [ ] FAIL

STEP 2: Navigate to Admin Dashboard
Result: [ ] PASS  [ ] FAIL

STEP 3: Find an approved case (look for "Vetted" tab)
Expected: Case found
Result: [ ] PASS  [ ] FAIL

STEP 4: Click on case to view details
Expected: Case details page loads
Result: [ ] PASS  [ ] FAIL

STEP 5: Click "Open vetting Form" link
Expected:
  - PDF downloads without error
  - No error page or message
  - PDF file appears in downloads

PDF download result: [ ] PASS  [ ] FAIL
Error message: _________________________

STEP 6: Verify PDF content
Open downloaded PDF and verify:
  - [ ] Case ID visible
  - [ ] Created timestamp in DD-MM-YYYY HH:MM format
  - [ ] Patient name displayed
  - [ ] Institution name shown
  - [ ] Radiologist name displayed
  - [ ] Vetting decision shown as "Approve"
  - [ ] Protocol listed
  - [ ] Vetted timestamp visible

PDF content check: [ ] PASS  [ ] FAIL
All fields present: [ ] YES  [ ] NO

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________

CLEANUP: Keep PDF for documentation
```

```
TEST CASE: BUG8-002 - PDF REJECTED CASE
Severity: CRITICAL
Precondition: Have a rejected case (status=rejected, decision=Reject)

STEP 1: Navigate to Admin Dashboard
Result: [ ] PASS  [ ] FAIL

STEP 2: Find rejected case (look for "Rejected" tab)
Expected: Case found
Result: [ ] PASS  [ ] FAIL

STEP 3: Click on case details
Expected: Case details page loads
Result: [ ] PASS  [ ] FAIL

STEP 4: Click "Open vetting Form"
Expected:
  - PDF downloads without error
  - No error occurs

PDF download result: [ ] PASS  [ ] FAIL

STEP 5: Verify rejected case PDF
Open PDF and verify:
  - [ ] Vetting decision shown as "Reject"
  - [ ] Protocol field NOT present (since rejected)
  - [ ] Rejection comment displayed
  - [ ] Timestamps formatted correctly

PDF content check: [ ] PASS  [ ] FAIL

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________
```

---

### Bug 9: No Edit of Approved Cases

**Objective**: Verify approved cases cannot be edited

```
TEST CASE: BUG9-001 - APPROVED CASE EDIT BUTTON
Severity: HIGH
Precondition: Logged in as admin, have an approved case

STEP 1: Navigate to Admin Dashboard
Result: [ ] PASS  [ ] FAIL

STEP 2: Go to "Vetted" tab
Expected: Vetted cases displayed
Result: [ ] PASS  [ ] FAIL

STEP 3: Find case with decision="Approve"
Expected: Case found
Result: [ ] PASS  [ ] FAIL

STEP 4: Click on case to view details
Expected: Case details page loads
Result: [ ] PASS  [ ] FAIL

STEP 5: Look for "Edit Case" button
Expected:
  - [ ] NO "Edit Case" button visible
  - [ ] Only "Back to Dashboard" button shown
  - [ ] Button area shows no edit option

Edit button visibility: 
  - [ ] PASS - No edit button
  - [ ] FAIL - Edit button present

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________
```

```
TEST CASE: BUG9-002 - APPROVED CASE DIRECT ACCESS
Severity: HIGH
Precondition: Have approved case ID: [copy from BUG9-001]

STEP 1: Manually navigate to edit URL
URL Pattern: /admin/case/{case_id}/edit
Example: /admin/case/20260131-ABC1/edit

STEP 2: Attempt to access edit page
Expected:
  - [ ] Access denied
  - [ ] 403 Forbidden error
  - [ ] Error message: "Cannot edit approved cases"
  - [ ] Redirect to case details or dashboard

Access result:
  - [ ] PASS - Access denied
  - [ ] FAIL - Edit form loaded (SECURITY ISSUE)

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________
```

```
TEST CASE: BUG9-003 - PENDING CASE EDIT ALLOWED
Severity: MEDIUM
Precondition: Have pending case

STEP 1: Navigate to Admin Dashboard
Result: [ ] PASS  [ ] FAIL

STEP 2: Go to "Pending" tab or "All" tab
Expected: Pending cases displayed
Result: [ ] PASS  [ ] FAIL

STEP 3: Find pending case
Expected: Case found
Result: [ ] PASS  [ ] FAIL

STEP 4: Click on case details
Expected: Case details page loads
Result: [ ] PASS  [ ] FAIL

STEP 5: Look for "Edit Case" button
Expected:
  - [ ] "Edit Case" button IS visible
  - [ ] Button is clickable

Edit button visibility: [ ] PASS  [ ] FAIL

STEP 6: Click "Edit Case"
Expected: Edit form loads successfully
Result: [ ] PASS  [ ] FAIL

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________

CLEANUP: Click Cancel to exit
```

---

### Bug 10: Updated Labels

**Objective**: Verify corrected label text

```
TEST CASE: BUG10-001 - CASE DETAILS LABELS
Severity: LOW
Precondition: Have any case, logged in as admin

STEP 1: Navigate to case details page
Expected: Case details load
Result: [ ] PASS  [ ] FAIL

STEP 2: Look for attachment links section
Expected: Links displayed at bottom of details

STEP 3: Verify link labels:
Expected text:
  - [ ] "Download referral" (NOT "Download attachments")
  - [ ] "Open vetting Form" (NOT "Open PDF")

Label verification:
  - Download link text: ____________________
    Expected: "Download referral"
    Result: [ ] PASS  [ ] FAIL

  - PDF link text: ____________________
    Expected: "Open vetting Form"
    Result: [ ] PASS  [ ] FAIL

RESULT: [ ] PASS  [ ] FAIL
Notes: _________________________________
```

---

## Final Validation

### Summary Scorecard

```
BUG #  | TEST CASE        | RESULT      | NOTES
-------|------------------|-------------|------------------
1      | User Creation    | [ ] PASS    | _________________
2      | Timestamps       | [ ] PASS    | _________________
3      | Column Sorting   | [ ] PASS    | _________________
4      | Form Readability | [ ] PASS    | _________________
5      | No Download      | [ ] PASS    | _________________
6-7    | Protocol Logic   | [ ] PASS    | _________________
8      | PDF Generation   | [ ] PASS    | _________________
9      | Edit Approval    | [ ] PASS    | _________________
10     | Label Updates    | [ ] PASS    | _________________

Total Passed: ___/9
Total Failed: ___/9
```

### Sign-Off

**Testing Results:**
- [ ] ALL TESTS PASSED - Ready for production
- [ ] MINOR ISSUES - Can proceed with caution
- [ ] MAJOR ISSUES - Do not proceed
- [ ] CRITICAL ISSUES - Immediate rollback required

**Tester Information:**
- Name: _________________________________
- Title: _________________________________
- Date: _________________________________
- Time: _________________________________
- Signature: ___________________________

**Approval:**
- [ ] Product Manager Approved: _____ Date: _____
- [ ] Tech Lead Approved: _____ Date: _____
- [ ] QA Lead Approved: _____ Date: _____

**Issues Found:**
1. ___________________________________ Severity: [ ] Critical [ ] High [ ] Medium [ ] Low
2. ___________________________________ Severity: [ ] Critical [ ] High [ ] Medium [ ] Low
3. ___________________________________ Severity: [ ] Critical [ ] High [ ] Medium [ ] Low

**Action Items:**
- [ ] No action items
- [ ] Items to address before next release
- [ ] Blockers requiring resolution

---

## Appendix: Test Data

### Test User Accounts
```
Admin Account:
  Username: admin
  Password: [keep secure]
  Role: Admin

Radiologist Test Account:
  Username: [radiologist account]
  Password: [keep secure]
  Role: Radiologist
  Linked to: [radiologist name]
```

### Test Case IDs
```
Created cases for testing:
- Case 1: [ID] Status: ______ Assigned to: ______
- Case 2: [ID] Status: ______ Assigned to: ______
- Case 3: [ID] Status: ______ Assigned to: ______
```

### Database Info
```
Database backup timestamp: ____________________
Database size: ____________ MB
Case count: ________
User count: ________
Institution count: ________
```
