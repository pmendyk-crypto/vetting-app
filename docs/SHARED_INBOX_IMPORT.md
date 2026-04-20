# Shared Inbox Import

RadFlow can import referral emails from a Microsoft 365 shared mailbox through Microsoft Graph.

## What The MVP Does

- An admin opens **Referral Inbox** from the worklist.
- The admin presses **Import now**.
- RadFlow reads the configured mailbox folder, imports each new email as a draft referral, and parses the message through the existing referral intake assistant.
- The admin reviews the extracted fields and creates a booking/case manually.
- No case is created automatically from email.

## Microsoft 365 Setup

Create a Microsoft Entra app registration for RadFlow inbox import.

Required app configuration:

- Client credentials: one client secret.
- Microsoft Graph application permission: `Mail.Read`.
- If you want RadFlow to move imported messages to processed/failed folders, use `Mail.ReadWrite` instead of `Mail.Read`.
- Admin consent granted for that permission.
- Restrict the app to the RadFlow mailbox only, preferably with Exchange Online application RBAC or an application access policy.

Recommended mailbox folders:

- `RadFlow Intake`
- `RadFlow Processed`
- `RadFlow Failed`

## Environment Variables

```text
GRAPH_TENANT_ID=
GRAPH_CLIENT_ID=
GRAPH_CLIENT_SECRET=
GRAPH_MAILBOX=radflow-intake@yourdomain.co.uk
GRAPH_INTAKE_FOLDER=RadFlow Intake
GRAPH_PROCESSED_FOLDER=RadFlow Processed
GRAPH_FAILED_FOLDER=RadFlow Failed
GRAPH_IMPORT_LIMIT=10
```

`GRAPH_PROCESSED_FOLDER` and `GRAPH_FAILED_FOLDER` are optional. If they are blank, RadFlow leaves imported emails in the intake folder and skips duplicates on later imports.

## Safety Notes

- Imported emails become review drafts, not cases.
- The admin must confirm the parsed details before case creation.
- Duplicate imports are skipped by Microsoft Graph message ID.
- The imported source email is retained as a supporting attachment when a case is created.
- Do not give the app broad mailbox access in production; scope it to the intake mailbox.

## Future Phase

- Scheduled automatic import.
- Delivery/failure dashboard.
- Allowed sender/domain rules per organisation.
- Automated filing of failed emails with an admin task reason.
- Two-way requestor email status updates.
