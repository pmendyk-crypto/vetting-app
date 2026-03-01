# Study Description Presets - Management Guide

## Overview
Your study description presets have been successfully loaded into the system with **full multitenant support**. This means:
- Each organization manages their own list of study descriptions
- Users only see study descriptions relevant to their organization
- No organization can access another organization's presets

---

## How Your Data is Organized

Your study descriptions are now available for these modalities:
- **CT** - 82 presets (Abdominal, Chest, Spine, Angiography, etc.)
- **MRI** - 54 presets (Brain, Spine, Cardiac, MSK, etc.)
- **XR** (X-Ray) - 42 presets (Chest, Skeletal survey, Limbs, etc.)
- **DEXA** - 10 presets (Bone density scans)
- **PET** - 14 presets (FDG, Cardiac, Brain, Oncology, etc.)

**Total:** 202 presets loaded

---

## How to Edit/Add Study Descriptions

### Method 1: UI Management Page (Recommended)
This is the easiest way for day-to-day management.

**Steps:**
1. Login as a **Superuser** of your organization
2. Go to **Admin → Settings → 📋 Study Presets**
3. You'll see a page with:
   - **Add New Preset** form at the top
   - **Your Organization's Presets** list below

### Add a New Preset
1. Select modality (MR, CT, XR, PET)
2. Enter description text
3. Click **Add Preset**
4. New preset appears immediately in the list

### Edit a Preset
1. Find the preset in the list
2. Click ** Edit** button
3. Modal dialog opens with current values
4. Change description or modality as needed
5. Click **Save Changes**

### Delete a Preset
1. Find the preset in the list
2. Click **Delete** button (⚠️ cannot be undone)
3. Preset is removed immediately

---

## How the Study Description Selector Works (Case Submission Form)

When a user submits a case at `/submit`:

1. **Select Modality** dropdown appears first (MR, CT, XR, PET, DEXA)
2. User selects a modality
3. **Study Description** field populates with a searchable dropdown
4. API call: `GET /api/study-descriptions/by-modality/{modality}`
   - Returns only presets for that modality from their organization
5. User can **type to search** - filters list in real-time
6. User clicks a preset to populate the field
7. Form submission includes the selected description

### Example Flow
```
User selects "CT" → 
API returns 82 CT presets for their org → 
User types "abdomen" → 
Filtered to show: "CT Abdomen", "CT Abdomen and pelvis", etc. → 
User clicks selection → 
Form field populated with chosen description
```

---

## Multitenant Architecture

### What This Means
- **Organization-level isolation**: Study descriptions are tied to `organization_id`
- **User-scoped access**: Users only see their organization's presets
- **Audit trail**: Each preset tracks `created_by` user ID
- **No cross-contamination**: Organization A cannot see/edit Organization B's presets

### Database Schema
```sql
CREATE TABLE study_description_presets (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL,        -- ← Multitenant key
    modality TEXT NOT NULL,                  -- CT, MRI, XR, PET, DEXA
    description TEXT NOT NULL,               -- The actual preset text
    created_at TEXT NOT NULL,                -- Timestamp
    updated_at TEXT NOT NULL,                -- Last modified
    created_by INTEGER NOT NULL,             -- User who created it
    UNIQUE(organization_id, modality, description)  -- ← Prevents duplicates per org
);

-- Efficient lookup by org + modality
INDEX idx_presets_org_modality (organization_id, modality)
```

### API Endpoints (All Multitenant)

**1. Get presets for case submission form**
```
GET /api/study-descriptions/by-modality/{modality}
Response: [{"id": 1, "description": "CT Abdomen"}, ...]
- Filters by user's organization automatically
- Returns only matching modality
```

**2. View/manage presets**
```
GET /settings/study-descriptions
- Superuser only
- Shows all presets for their organization
- Provides add/edit/delete UI
```

**3. Add new preset**
```
POST /settings/study-descriptions/add
Form: modality, description
- Automatically uses user's organization_id
- Prevents duplicates within the org
```

**4. Edit preset**
```
POST /settings/study-descriptions/edit/{preset_id}
Form: modality, description
- Only allows editing if preset belongs to user's org
```

**5. Delete preset**
```
POST /settings/study-descriptions/delete/{preset_id}
- Only allows deletion if preset belongs to user's org
```

---

## Future Workflow for Additions/Changes

### Scenario 1: Add New Exam Types
**Problem:** New modality like "Ultrasound" isn't in the system

**Solution:**
1. Contact app administrators to add `US` (Ultrasound) to modality dropdown
2. Core team updates template dropdown
3. Once ready, you use UI to add presets
4. Users can immediately select US and see your presets

### Scenario 2: Bulk Updates
**If you need to add many presets at once:**

**Option A (Recommended):** Use the UI multiple times
- Click add → fill form → save
- Takes ~30 seconds per preset
- Safest approach, no technical skills needed

**Option B (Advanced):** SQL migration file
- Create new migration file: `004_update_study_descriptions.sql`
- Format:
```sql
INSERT INTO study_description_presets (organization_id, modality, description, created_at, updated_at, created_by) 
VALUES (1, 'CT', 'New CT Exam Name', datetime('now'), datetime('now'), 1);
```
- Requires database access

### Scenario 3: Removing/Archiving Old Presets
**If exam descriptions no longer match your institution:**

1. Go to `/settings/study-descriptions`
2. Click **Delete** on old preset
3. Done - it won't appear in dropdown anymore
4. Users with existing cases keep the old description (orphaned data is safe)

### Scenario 4: Correcting Typos
1. Go to `/settings/study-descriptions`
2. Find the preset with typo
3. Click **Edit**
4. Fix the text
5. Click **Save Changes**

---

## Important Notes

### Uniqueness Constraint
- **Per organization, per modality**: Cannot have two identical descriptions in same org
  - ❌ Organization 1 cannot have two "CT Abdomen" for CT
  - ✅ Organization 1 can have "CT Abdomen" AND "CT Abdomen and pelvis"
  - ✅ Organization 1 and Organization 2 can each have "CT Abdomen"

### User Experience
- Case submitter selects modality → Gets **all** presets for that modality
- Type ahead filtering narrows list as they type
- Much faster than free-text entry
- Ensures consistency in study descriptions across all cases

### Backup & Recovery
- All your presets are stored in database
- Migration file (`003_study_description_presets.sql`) has initial load
- To backup: Export database or use `/export` endpoint (if available)

---

## Access Control

| Role | Can View | Can Add | Can Edit | Can Delete |
|------|----------|---------|----------|-----------|
| Superuser (own org) | ✅ All | ✅ Yes | ✅ Yes | ✅ Yes |
| Superuser (other org) | ❌ No | ❌ No | ❌ No | ❌ No |
| Regular User | Sees in dropdown | ❌ No | ❌ No | ❌ No |
| Admin | ✅ All | ✅ Yes | ✅ Yes | ✅ Yes |

---

## Troubleshooting

### "Study descriptions not appearing in dropdown"
- **Check:** Select correct modality
- **Check:** You're logged in to correct organization
- **Check:** Presets were actually created (view `/settings/study-descriptions`)

### "Duplicate preset error when adding"
- You already have this exact description for this modality
- Either delete old one first, or use different description text

### "Can't see other organization's presets"
- **This is correct behavior** - multitenant isolation working as designed
- Each org has independent list
- Contact admin if you need to share/sync with another org

### Presets disappeared after case edits
- Editing cases with old descriptions is safe
- Their case keeps original text
- Just add preset back if needed for new cases

---

## Integration Points

Your study descriptions are used in:

1. **Case Submission Form** (`/submit`)
   - Modality → Description dropdown (searchable)
   
2. **Radiologist Case Viewing**
   - Displays selected description (read-only)
   
3. **Case History/Archive**
   - Original description preserved regardless of later edits

4. **Reports/Analytics** (future)
   - Can group cases by standard descriptions
   - Enables better auditing and quality metrics

---

## Quick Reference

### Current Status
✅ **202 study descriptions loaded** across all modalities
✅ **Multitenant support** - organization-level isolation
✅ **Full CRUD interface** - add/edit/delete via UI
✅ **Form integration** - searchable dropdown in case submission
✅ **Future-proof** - easy to add/modify presets

### Next Steps
1. Test case submission form with your modality/descriptions
2. Add any organization-specific exam names you need
3. Train users on using the dropdown searcher
4. Monitor for any missing descriptions and add as needed
