# Vetting App - Architecture & Structure Guide

## Overview
This is a **FastAPI-based web application** for managing medical case vetting and radiologist workflows. It uses SQLite/PostgreSQL for data storage and Jinja2 templates for the frontend.

---

## 1. Core Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend Framework** | FastAPI (Python) |
| **Database** | SQLite (default) / PostgreSQL (production) |
| **Frontend** | Jinja2 Templates + HTML/CSS |
| **Session Management** | Starlette SessionMiddleware |
| **Static Assets** | CSS, Images |
| **Document Generation** | ReportLab (PDF generation) |

---

## 2. Application Hierarchy & User Roles

```
┌─────────────────────────────────────────────────────────┐
│                 VETTING APP                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │   ADMIN ROLE     │  │ RADIOLOGIST ROLE │             │
│  └────────┬─────────┘  └────────┬─────────┘             │
│           │                      │                       │
│    ┌──────┴──────┐        ┌──────┴──────┐              │
│    │             │        │             │              │
│  Admin      Settings    Queue      Dashboard           │
│  Dashboard  Management  Page       Page                │
│    │             │        │             │              │
│  Cases      Institutions  Cases    Case Details       │
│  Details    Radiologists  Under     & Actions         │
│  & Vetting  Protocols     Review                       │
│             Users                                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema

```
┌──────────────────────────────────────────────────────────────┐
│                        DATABASE                               │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────┐  ┌──────────────────┐                  │
│  │   CASES         │  │  INSTITUTIONS    │                  │
│  ├─────────────────┤  ├──────────────────┤                  │
│  │ id (PRIMARY KEY)├──┤ id (FK)          │                  │
│  │ created_at      │  │ name             │                  │
│  │ patient_*       │  │ sla_hours        │                  │
│  │ institution_id  │  │ created_at       │                  │
│  │ status          │  │ modified_at      │                  │
│  │ decision        │  └──────────────────┘                  │
│  │ vetted_at       │                                         │
│  │ radiologist     │  ┌──────────────────┐                  │
│  └─────────────────┘  │  RADIOLOGISTS    │                  │
│         │             ├──────────────────┤                  │
│         │             │ name (PRIMARY)   │                  │
│  ┌──────┴──────────┐  │ email            │                  │
│  │  PROTOCOLS      │  │ surname          │                  │
│  ├─────────────────┤  │ gmc              │                  │
│  │ id (PRIMARY KEY)│  │ speciality       │                  │
│  │ name            │  └──────────────────┘                  │
│  │ institution_id  │                                         │
│  │ instructions    │  ┌──────────────────┐                  │
│  │ is_active       │  │    USERS         │                  │
│  └─────────────────┘  ├──────────────────┤                  │
│         │             │ username (PK)    │                  │
│         │             │ role             │                  │
│         │             │ radiologist_name │                  │
│  ┌──────┴──────────┐  │ pw_hash_hex      │                  │
│  │   CONFIG        │  │ salt_hex         │                  │
│  ├─────────────────┤  └──────────────────┘                  │
│  │ key (PRIMARY)   │                                         │
│  │ value           │                                         │
│  └─────────────────┘                                         │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Page & Route Hierarchy

### A. PUBLIC/AUTHENTICATION PAGES

| Route | Template | Purpose |
|-------|----------|---------|
| `/` | `landing.html` | Public landing page (first visit) |
| `/login` | `login.html` | User login page |
| `/forgot-password` | `forgot_password.html` | Password reset page |
| `/logout` | (redirect) | Clear session & logout |

---

### B. ADMIN ROLE PAGES

```
ADMIN DASHBOARD (/admin)
├── admin_case.html
├── Shows all cases with status (pending/vetted)
├── Filters & sorting
├── Quick actions
│
├─ VIEW CASE DETAILS (/admin/case/{case_id})
│  └── case_edit.html (read-only view of submission)
│
├─ EDIT CASE (/admin/case/{case_id}/edit) [POST]
│  └── case_edit.html (edit form)
│  └── Update case details, notes, assignments
│
└─ EXPORT (/admin.csv) [GET]
   └── CSV download of all cases
```

**Admin Functions:**
- View all submitted cases
- Filter by status, date, institution, radiologist
- Assign cases to radiologists
- Add/edit case details & admin notes
- Monitor SLAs (Service Level Agreements)
- Export case data to CSV

---

### C. RADIOLOGIST ROLE PAGES

```
RADIOLOGIST QUEUE (/radiologist)
├── radiologist_queue.html
├── Shows cases assigned to this radiologist
├── Status: pending, under review
│
├─ RADIOLOGIST DASHBOARD (/radiologist) [ALTERNATE VIEW]
│  └── radiologist_dashboard.html
│  └── Different view of assigned cases
│
└─ VET A CASE (/vet/{case_id})
   ├── vet.html
   ├── Radiologist review form
   ├── Decision options:
   │  ├── Approve
   │  ├── Reject
   │  └── Approve with comment
   └── Submit decision [POST /vet/{case_id}]
```

**Radiologist Functions:**
- View assigned cases in queue
- Review case details
- Make vetting decisions (Approve/Reject/Comment)
- Add decision comments
- Track completed cases

---

### D. CASE SUBMISSION PAGE

```
CASE SUBMISSION (/submit)
├── submit.html
├── Form for submitting new cases
├── Fields:
│  ├── Patient name (first, surname)
│  ├── Referral ID
│  ├── Institution dropdown
│  ├── Protocol dropdown
│  ├── Study description
│  └── File upload (images/attachments)
│
├─ POST /submit
│  └── Process form & file upload
│  └── Create new case in database
│  └── Generate unique case ID
│
└─ CONFIRMATION (/submitted/{case_id})
   └── submitted.html
   └── Show confirmation & case ID
```

---

### E. SETTINGS MANAGEMENT PAGE

```
SETTINGS (/settings)
└── settings.html
    │
    ├─ INSTITUTIONS TAB
    │  ├── POST /settings/institution/add
    │  ├── POST /settings/institution/edit/{inst_id}
    │  └── POST /settings/institution/delete/{inst_id}
    │  └── Manage hospital/clinic names & SLAs
    │
    ├─ RADIOLOGISTS TAB
    │  ├── POST /settings/radiologist/add
    │  ├── POST /settings/radiologist/delete
    │  ├── GET /settings/radiologist/edit/{name}
    │  └── POST /settings/radiologist/update
    │  └── Manage radiologist profiles
    │
    ├─ PROTOCOLS TAB
    │  ├── POST /settings/protocol/add
    │  ├── POST /settings/protocol/edit/{protocol_id}
    │  ├── POST /settings/protocol/delete
    │  └── POST /settings/protocol/delete/{protocol_id}
    │  └── Manage scanning protocols
    │
    └─ USERS TAB
       ├── POST /settings/user/add
       ├── POST /settings/user/delete
       ├── POST /settings/user/edit
       └── Manage system users & roles
```

---

### F. FILE & ATTACHMENT ENDPOINTS

| Route | Method | Purpose |
|-------|--------|---------|
| `/case/{case_id}/attachment` | GET | Download uploaded file |
| `/case/{case_id}/attachment/inline` | GET | View file inline (browser) |
| `/case/{case_id}/pdf` | GET | Generate & download PDF report |

---

## 5. Data Flow Diagrams

### Flow 1: Case Submission

```
┌──────────────┐
│  Submit Form │
│  (/submit)   │
└──────┬───────┘
       │
       │ User fills form & uploads file
       │
       ▼
┌──────────────────────┐
│  POST /submit        │
│  - Store file        │
│  - Generate case ID  │
│  - Create DB record  │
│  - Set status=pending│
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  /submitted/{case_id}│
│  Show confirmation   │
└──────────────────────┘
```

### Flow 2: Case Vetting (Admin → Radiologist → Admin)

```
┌──────────────────┐
│  Admin Dashboard │
│  (/admin)        │
└────────┬─────────┘
         │
         │ Assign case to radiologist
         │
         ▼
┌──────────────────────────┐
│  Radiologist Queue       │
│  (/radiologist)          │
│  Shows assigned cases    │
└────────┬─────────────────┘
         │
         │ Click to review
         │
         ▼
┌──────────────────┐
│  Vet Case        │
│  (/vet/{case_id})│
│  Review details  │
│  Make decision   │
└────────┬─────────┘
         │
         │ Submit decision
         │ POST /vet/{case_id}
         │
         ▼
┌──────────────────────────┐
│  Update Case Record      │
│  - Set status=vetted     │
│  - Store decision        │
│  - Record decision_date  │
│  - Calculate TAT         │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────┐
│  Admin Dashboard     │
│  Shows updated case  │
│  (now in vetted list)│
└──────────────────────┘
```

### Flow 3: Settings Management

```
┌──────────────────┐
│  Settings Page   │
│  (/settings)     │
└────────┬─────────┘
         │
    ┌────┴────┬────────┬───────┐
    │          │        │       │
    ▼          ▼        ▼       ▼
Institutions Radiologists Protocols Users
    │          │        │       │
    │          │        │       │
 Add/Edit   Add/Edit  Add/Edit Add/Edit
 Delete     Delete    Delete   Delete
```

---

## 6. Key Features by Page

| Page | Key Features | User Role |
|------|--------------|-----------|
| **Admin Dashboard** | Case list, filters, status tracking, SLA monitoring | Admin |
| **Radiologist Queue** | Case assignments, pending review count, quick actions | Radiologist |
| **Case Submission** | Multi-field form, file upload, validation | Public/All |
| **Case Details** | View/edit patient info, notes, protocol, decision | Admin & Radiologist |
| **Vetting** | Decision form (Approve/Reject/Comment), comments field | Radiologist |
| **Settings** | CRUD operations for Institutions, Users, Protocols, Radiologists | Admin |
| **CSV Export** | Download all cases with metadata | Admin |

---

## 7. File Organization

```
Vetting App/
├── app/
│   └── main.py (FastAPI routes & business logic - 1940 lines)
│
├── templates/ (Jinja2 HTML templates)
│   ├── landing.html (public entry point)
│   ├── login.html & forgot_password.html (auth)
│   ├── index.html (home redirect)
│   ├── admin_case.html (admin dashboard)
│   ├── case_edit.html (case detail/edit)
│   ├── radiologist_queue.html (radiologist queue)
│   ├── radiologist_dashboard.html (alt dashboard)
│   ├── radiologist_edit.html (radiologist profile edit)
│   ├── submit.html (case submission form)
│   ├── submitted.html (submission confirmation)
│   ├── vet.html (vetting decision form)
│   ├── settings.html (admin settings)
│   └── home.html (user home page)
│
├── static/
│   ├── css/
│   │   ├── login.css (login page styling)
│   │   └── site.css (global styling)
│   └── images/ (app images & icons)
│
├── uploads/ (user-submitted files)
│
└── Database Files:
    ├── hub.db (SQLite default)
    └── or PostgreSQL (DATABASE_URL env var)
```

---

## 8. Dependencies & Connections

```
┌─────────────────────────────────────────────────────────────┐
│                    EXTERNAL DEPENDENCIES                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  FastAPI       ← Core framework                              │
│  Starlette     ← Session & middleware support                │
│  Jinja2        ← Template rendering                          │
│  SQLAlchemy    ← PostgreSQL support (optional)               │
│  ReportLab     ← PDF generation                              │
│  SQLite3       ← Default database                            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Authentication & Authorization Flow

```
┌──────────────────┐
│  Login Page      │ (POST /login)
└────────┬─────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Verify Credentials                 │
│  - Check users table                │
│  - Hash password & compare          │
│  - Retrieve user role & metadata    │
└────────┬────────────────────────────┘
         │
    ┌────┴─────┬───────────┐
    │ SUCCESS   │  FAILURE  │
    ▼           ▼
┌──────────┐  ┌──────────┐
│ Create   │  │ Show     │
│ Session  │  │ Error    │
│ Redirect │  │ Message  │
│ to /     │  └──────────┘
└──────────┘
    │
    ▼
┌────────────────────────────────────┐
│  Session Middleware                │
│  - Set session cookie              │
│  - Store user info in session      │
│  - Enable role-based access        │
└────────────────────────────────────┘
```

---

## 10. Quick Reference: Route Summary

**35 Total Routes:**

| Category | Count | Routes |
|----------|-------|--------|
| Authentication | 5 | /, /login (GET/POST), /forgot-password (GET/POST), /logout |
| Admin | 6 | /admin, /admin.csv, /admin/case/{id} (GET/view), /admin/case/{id}/edit (GET/POST) |
| Radiologist | 2 | /radiologist, /vet/{case_id} (GET/POST) |
| Submission | 3 | /submit (GET/POST), /submitted/{case_id} |
| Settings | 12 | /settings + institution/radiologist/protocol/user CRUD ops |
| Files | 3 | /case/{id}/attachment, /attachment/inline, /pdf |

---

## 11. Important Concepts

### Case Status Flow
```
pending → (assigned to radiologist) → (radiologist reviews) → vetted
```

### Decision Types
- **Approve**: Case accepted
- **Reject**: Case rejected
- **Approve with comment**: Approved + notes

### SLA (Service Level Agreement)
- Stored per institution
- Tracks time from case creation to vetting completion
- Formatted as: `Xd XXh XXm` (days, hours, minutes)

---

## 12. Environment Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `DB_PATH` | SQLite database location | `./hub.db` |
| `UPLOAD_DIR` | File upload storage path | `./uploads` |
| `DATABASE_URL` | PostgreSQL URL (optional) | None |
| `APP_SECRET` | Session encryption key | `dev-secret-change-me` |
| `PORT` | Server port (Docker) | `8080` |

---

## Summary

Your Vetting App is a **multi-role medical case management system** with:

1. **Two main user roles** (Admin & Radiologist)
2. **Clear data flow** from case submission → admin review → radiologist vetting
3. **Comprehensive settings** for managing institutions, users, and protocols
4. **Database-backed** with support for SQLite and PostgreSQL
5. **Document export** capabilities (CSV & PDF)
6. **SLA tracking** for performance monitoring

The app follows a **typical web application pattern** with FastAPI backend + Jinja2 frontend, organized by user roles and workflows.
