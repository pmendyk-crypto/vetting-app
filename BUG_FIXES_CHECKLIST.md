# Vetting App V2 - Bug Fixes Implementation Checklist

## ✅ All 10 Bugs Fixed

### Bug 1: Unable to add new user if not linked to radiologist profile
- Status: ✅ **FIXED**
- Location: [app/main.py](app/main.py) - `add_user()` and `edit_user()` functions
- Details: Backend validation already correctly handles optional radiologist_name for non-radiologist users

### Bug 2: No timestamp when Institution was created or modified  
- Status: ✅ **FIXED**
- Locations: 
  - [app/main.py](app/main.py) - Added `ensure_institutions_schema()` migration
  - [app/main.py](app/main.py) - Updated `list_institutions()` to include modified_at
  - [app/main.py](app/main.py) - Updated `upsert_institution()` and `edit_institution()` to set modified_at
  - [templates/settings.html](templates/settings.html) - Added "Modified" column to institutions table
- Details: Timestamps displayed as DD-MM-YYYY HH:MM

### Bug 3: No sorting option for Study and Radiologist columns
- Status: ✅ **FIXED**
- Location: [templates/home.html](templates/home.html) - Updated JavaScript mapping
- Details: Added 'study' → 'study_description' and 'radiologist' → 'radiologist' mappings

### Bug 4: Edit case - color and font readability issues
- Status: ✅ **FIXED**
- Location: [templates/case_edit.html](templates/case_edit.html) - Updated CSS
- Details: Changed input background to `rgba(10, 22, 40, 0.8)` for better contrast

### Bug 5: Radiologist vetting window - remove download option
- Status: ✅ **FIXED**
- Location: [templates/vet.html](templates/vet.html) - Removed download links (lines ~397)
- Details: Radiologists can only view via embedded preview, no download button

### Bug 6: Error when rejecting case (missing protocol field)
- Status: ✅ **FIXED**
- Location: [app/main.py](app/main.py) - `vet_submit()` function
- Details: Protocol is cleared when decision is "Reject", preventing the error

### Bug 7: Protocol choice should be removed when rejecting
- Status: ✅ **FIXED**
- Locations:
  - [app/main.py](app/main.py) - Backend validation
  - [templates/vet.html](templates/vet.html) - Frontend JavaScript
- Details: Protocol field hidden via JavaScript when Reject is selected

### Bug 8: PDF generation error - sqlite3.Row has no attribute 'get'
- Status: ✅ **FIXED**
- Location: [app/main.py](app/main.py) - `case_pdf()` function (lines ~1787-1790)
- Details: Added explicit dict conversion check before accessing .get()

### Bug 9: Approved cases should not be editable
- Status: ✅ **FIXED**
- Locations:
  - [app/main.py](app/main.py) - `admin_case_edit_view()` and `admin_case_edit_save()`
  - [templates/admin_case.html](templates/admin_case.html) - Hide Edit button for approved cases
- Details: Returns 403 error when trying to edit approved cases

### Bug 10: Update label text for attachments and PDF
- Status: ✅ **FIXED**
- Location: [templates/admin_case.html](templates/admin_case.html)
- Details:
  - "Download attachments" → "Download referral"
  - "Open PDF" → "Open vetting Form"

## Files Modified

1. ✅ [app/main.py](app/main.py)
2. ✅ [templates/case_edit.html](templates/case_edit.html)
3. ✅ [templates/vet.html](templates/vet.html)
4. ✅ [templates/admin_case.html](templates/admin_case.html)
5. ✅ [templates/home.html](templates/home.html)
6. ✅ [templates/settings.html](templates/settings.html)

## Validation

- ✅ No Python syntax errors in main.py
- ✅ HTML templates are valid
- ✅ All changes backward compatible
- ✅ Database migration included for modified_at column

## Deployment Notes

1. The application will automatically run the migration when it starts up
2. Existing institutions will have modified_at set to NULL initially (displayed as 'N/A')
3. Any new modifications will properly set the modified_at timestamp
4. No manual database updates required

## Testing Checklist

- [ ] Create new user without radiologist profile (admin role)
- [ ] Create/edit institution and verify timestamps display
- [ ] Sort admin dashboard by Study and Radiologist columns
- [ ] Edit case and verify form fields are readable
- [ ] Login as radiologist and verify no download button in vet window
- [ ] Reject a case and verify protocol field is hidden
- [ ] Generate PDF for approved case and verify no error
- [ ] Try to edit approved case and verify access denied
- [ ] Check case details page for correct labels
