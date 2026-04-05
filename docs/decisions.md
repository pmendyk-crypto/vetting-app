# Decisions

- Decision: keep the current organisation-aware main app path and avoid reviving the alternate router UX until the codebase is simpler.
- Decision: no major new features until structure is improved.
- Decision: keep documentation current before large refactoring work.
- Decision: owner governance should use the `/owner*` route family, not the older `/mt/*` and unmounted router path.
- Decision: architecture refactoring should proceed after the documentation baseline is validated.

## Notes

These decisions align with the current technical risk profile:

- large monolithic route module
- mixed schema-management strategy
- coexistence of current membership-based access with legacy compatibility paths

## Operating Rules (Current)

- organisation-aware workflows are active in the main app
- no organisation-switching UI is exposed through the old alternate router flow
- owner/superuser governance happens through `/owner*`
- the alternate multi-tenant router module remains non-live
- multi-channel intake expansion remains paused until core stabilization milestones are met

## In-Scope Features

- authentication, account management, and MFA
- password reset
- owner organisation management
- admin dashboard and reporting
- organisation settings and user management
- practitioner vetting workflow
- file attachments
- PDF generation
- CSV export
- referral parser trial
- iRefer search
- practitioner notifications
