# Decisions

- Decision: focus on single-client deployment for now
- Decision: no major new features until structure is improved
- Decision: codebase documentation before refactoring
- Decision: multi-tenant platform development paused
	Reason: complexity obscures architecture and increases operational risk.
- Decision: architecture refactoring will begin after Workstream 1 documentation is validated
	Reason: ensures cleanup is structured and avoids accidental system breakage.

## Notes
These decisions align with current technical risk profile: large monolithic route module, mixed schema-management strategy, and partial multi-tenant wiring.
Refactoring and hardening should proceed after documentation baseline is complete.

## Operating Rules (Current)
- One active client only.
- No organisation switching in the UI.
- No multi-tenant platform workflows exposed to users.
- Existing organisation-related schema may remain where needed for compatibility.
- Multi-tenant expansion remains paused until core stabilization milestones are met.

## In-Scope Features
- Authentication
- Case intake
- Radiologist vetting workflow
- Admin dashboard
- File attachments
- PDF generation
- CSV export
- Referral parser trial
- iRefer search
- Radiologist email notifications
