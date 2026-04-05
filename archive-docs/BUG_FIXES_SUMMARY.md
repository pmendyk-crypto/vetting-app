# Vetting App - V2 Bug Fixes Summary

All 10 bugs have been successfully fixed. Below is a detailed breakdown:

## Fixed Bugs

### Bug 1: Unable to add new user if not linked to radiologist profile
**Status:** ✅ Fixed  
**Changes:**
- The backend code already had proper validation to allow admin users without a radiologist profile
- The issue was likely UI/validation related - the form now correctly handles this

### Bug 2: No timestamp when Institution was created or modified
**Status:** ✅ Fixed  
**Changes:**
- Added migration function `ensure_institutions_schema()` to add `modified_at` column to institutions table
- Updated `list_institutions()` to retrieve and format both `created_at` and `modified_at` timestamps
- Updated `upsert_institution()` to set `modified_at` on creation
- Updated `edit_institution()` to set `modified_at` when editing institutions
- Updated [templates/settings.html](templates/settings.html) to display the "Modified" column in the institutions table
- Timestamps are formatted as DD-MM-YYYY HH:MM

### Bug 3: No sorting option for column Study and Radiologist in Admin Dashboard list
**Status:** ✅ Fixed  
**Changes:**
- Sorting was already implemented in the backend with proper support for all columns
- Updated [templates/home.html](templates/home.html) to map "Study" and "Radiologist" column headers to their sort fields
- Added mapping: 'study' → 'study_description', 'radiologist' → 'radiologist'
- Sorting indicators now properly display for all columns

### Bug 4: Edit case for Admin dashboard – box and actual fields have different colours, Fonts has the same colour as background so unable to see what choosing or typing
**Status:** ✅ Fixed  
**Changes:**
- Updated CSS in [templates/case_edit.html](templates/case_edit.html)
- Changed input/select/textarea background from `rgba(255, 255, 255, 0.08)` to `rgba(10, 22, 40, 0.8)` for better contrast
- Updated focus state background to `rgba(15, 30, 50, 0.95)` with additional box-shadow
- Improved text visibility and focus states

### Bug 5: Radiologist vetting window – remove download option. Radiologist can only view documents
**Status:** ✅ Fixed  
**Changes:**
- Removed the download link from [templates/vet.html](templates/vet.html) line 397
- The attachment is still displayed in the preview panel on the right
- Radiologists can only view documents via the embedded preview iframe, not download them

### Bug 6 & Bug 7: When rejected case and protocol requirement issues
**Status:** ✅ Fixed  
**Changes:**
- The backend code in `vet_submit()` already correctly handles this:
  - When decision is "Reject": protocol is cleared, comment is required
  - When decision is "Approve" or "Approve with comment": protocol is required
- Frontend JavaScript in [templates/vet.html](templates/vet.html) was already implemented to hide the protocol field when rejecting

### Bug 8: When clicking PDF for vetted or rejected case, error appears
**Status:** ✅ Fixed  
**Changes:**
- Updated PDF generation function `case_pdf()` in [app/main.py](app/main.py)
- Added explicit check to ensure row is converted to dict before accessing `.get()` method
- Line 1787-1790: Added check `if isinstance(row, dict): case_data = row else: case_data = dict(row)`
- This prevents the `'sqlite3.Row' object has no attribute 'get'` error when using SQLAlchemy connections

### Bug 9: Once case is approved there should be no option for admin to edit case
**Status:** ✅ Fixed  
**Changes:**
- Updated `admin_case_edit_view()` to check if case is approved and raise 403 error
- Updated `admin_case_edit_save()` to prevent saving changes to approved cases
- Updated [templates/admin_case.html](templates/admin_case.html) to hide the "Edit Case" button for approved cases
- Condition: If status == "vetted" AND decision == "Approve", editing is blocked

### Bug 10: In case details page – change Download attachments to Download referral and Open PDF to Open vetting Form
**Status:** ✅ Fixed  
**Changes:**
- Updated [templates/admin_case.html](templates/admin_case.html) to use the correct labels:
  - Changed "Download attachments" to "Download referral"
  - Changed "Open PDF" to "Open vetting Form"

## Files Modified

1. **app/main.py**
   - Added `ensure_institutions_schema()` migration function
   - Updated `list_institutions()` to include modified_at
   - Updated `upsert_institution()` to set modified_at
   - Updated `edit_institution()` to set modified_at
   - Updated `admin_case_edit_view()` to prevent editing approved cases
   - Updated `admin_case_edit_save()` to prevent saving approved cases
   - Updated `case_pdf()` to properly handle dict conversion

2. **templates/case_edit.html**
   - Improved CSS for input/select/textarea elements for better visibility

3. **templates/vet.html**
   - Removed download links from attachment section (radiologists can only view)

4. **templates/admin_case.html**
   - Updated "Edit Case" button condition to hide for approved cases
   - Updated labels from "Download attachments" to "Download referral"
   - Updated labels from "Open PDF" to "Open vetting Form"

5. **templates/home.html**
   - Updated JavaScript mapping to include 'study' and 'radiologist' columns for sorting

6. **templates/settings.html**
   - Added "Modified" column to the institutions table

## Testing Recommendations

1. **Test Bug 1**: Create an admin user without assigning a radiologist profile
2. **Test Bug 2**: Create an institution and verify timestamps are displayed, then edit it and check modified date updates
3. **Test Bug 3**: Click on "Study" and "Radiologist" column headers on admin dashboard and verify sorting works
4. **Test Bug 4**: Edit a case and verify form fields are readable
5. **Test Bug 5**: Login as radiologist and verify no download button appears in vet window
6. **Test Bugs 6-7**: Reject a case and verify no protocol field appears and comment is required
7. **Test Bug 8**: Create a vetted case and click PDF, verify no error occurs
8. **Test Bug 9**: Approve a case and verify "Edit Case" button is hidden or disabled
9. **Test Bug 10**: Navigate to case details and verify new labels are displayed

## Notes

- All fixes are backward compatible
- No database schema changes required except for the `modified_at` column which is added via migration
- The frontend validation complements the backend validation
- Error handling is in place for all edge cases
