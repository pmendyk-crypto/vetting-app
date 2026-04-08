# Owner Portal Roadmap

## Purpose

This document captures the current direction for the RadFlow owner portal so the product and implementation decisions are not lost in chat.

The owner portal is the platform-level control area used by the Lumos/RadFlow owner account. It is distinct from a tenant organisation admin workspace.

## Current Position

The current owner portal already supports the core bootstrap flow:

- create an organisation
- create its first admin user
- edit organisation name, slug, and active status
- view organisation users and institutions
- add, edit, deactivate, reset password, and delete tenant users

This is enough to support initial staging onboarding and a first live client with some operational care.

## Phase 1: First Client Readiness

Goal: support onboarding and operating the first client safely without overbuilding.

### Must-Have

- owner can create the first organisation
- owner can create the first organisation admin
- organisation admin can log in and manage their own tenant data
- owner can reset organisation user passwords
- owner can see a basic organisation summary

### Should-Have

- auto-generate organisation slug from organisation name unless manually overridden
- rename `Open Admin Workspace` to `Open Global Admin View`
- keep owner actions clearly separated from tenant admin actions

### Operational Model

Recommended flow for the first client:

1. owner creates the organisation and first admin
2. organisation admin logs in
3. organisation admin sets up institutions, practitioners, protocols, presets, and report settings
4. owner only returns for support, password resets, or tenant-level maintenance

## Phase 2: Multi-Client Readiness

Goal: support multiple client organisations cleanly inside one shared production environment using `org_id` as the tenant boundary.

### Priority Enhancements

- tenant-aware support access
  - owner selects which tenant to enter
  - owner enters an org-scoped admin view intentionally
  - every access is audit logged

- onboarding checklist per organisation
  - organisation created
  - first admin created
  - institution added
  - practitioner added
  - protocols loaded
  - presets available
  - intake tested
  - reporting configured

- tenant setup summary
  - show whether a tenant is operationally ready
  - highlight missing setup items at a glance

- tenant settings overview
  - report header/footer
  - intake token/link
  - notification settings
  - future return-email configuration

- organisation lifecycle controls
  - active
  - suspended
  - archived

- platform support search
  - search by organisation name
  - search by admin email
  - search by username
  - search by case ID

### Future Admin Access Model

The long-term intention is:

- `Open Global Admin View` remains a platform-level workspace for support and cross-tenant oversight
- a separate owner action allows selecting a tenant and opening that tenant's admin context
- tenant-entry actions should be explicit and auditable

This is preferable to silently reusing the normal admin workspace because it avoids ambiguity about which tenant context the owner is operating inside.

## Recommended Build Order

1. improve owner portal UX for first-client onboarding
2. add tenant support entry with explicit tenant selection
3. add audit logging for owner tenant access
4. add onboarding readiness checklist per organisation
5. add tenant settings summary
6. add organisation lifecycle controls

## Notes

- staging and production must remain on separate databases
- production should remain a shared multi-tenant environment unless a future client requires dedicated infrastructure
- `org_id` remains the primary tenant boundary in the application
- owner-level features should not weaken tenant isolation
