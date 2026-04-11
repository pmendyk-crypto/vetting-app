# Azure Code Deployment

This repo deploys to Azure App Service through GitHub Actions code publishing.
Azure App Service is the only configured staging and production hosting target in this repository.

## Current Environment Flow

1. Work locally from `develop`.
2. Push `develop` to deploy staging.
3. Validate staging on Azure.
4. Merge or promote `develop` into `main`.
5. Push `main` to deploy production.

## Azure App Services

- Staging app: `lumosradflow-staging`
- Production app: `lumosradflow-prod`
- Shared App Service plan: `ASP-RadFlow-a377`

## GitHub Workflows

- `.github/workflows/deploy-staging.yml` deploys `develop` to `lumosradflow-staging`
- `.github/workflows/deploy-production.yml` deploys `main` to `lumosradflow-prod`
No other production deployment workflow is configured in this repository.

## Required GitHub Secrets

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

GitHub Actions uses Azure OpenID Connect through `azure/login@v2`. Publish profile secrets are not required for the active workflow, and Azure basic publishing authentication does not need to be enabled for GitHub deployment.

## Azure App Configuration

Use Python 3.12 on Linux for the GitHub Actions code deployment path.

Recommended app settings:

- `APP_BASE_URL`
- `APP_SECRET`
- `DATABASE_URL`
- `AZURE_STORAGE_CONNECTION_STRING`
- `REFERRAL_BLOB_CONTAINER=referrals`
- `SCM_DO_BUILD_DURING_DEPLOYMENT=1`
- `ENABLE_ORYX_BUILD=true`
- `REFERRAL_FILE_TTL_DAYS=7`
- `CASE_RECORD_TTL_DAYS=28`
- `LOGO_DARK_URL=/static/images/logo-light.png`
- `ALLOW_DIAGNOSTIC_ENDPOINT=false` for production unless intentionally needed

Optional app settings when relevant:

- SMTP settings for password reset and practitioner notifications
- `IREFER_API_KEY`

Environment-specific notes:

- staging can keep `APP_BASE_URL` on the Azure default hostname
- production should use the live external hostname for `APP_BASE_URL`

## Startup Commands

- `bash startup.sh` is the repo-provided startup path if you want Gunicorn with Uvicorn workers
- the repo also supports direct startup with:
  `uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`

## Manual Script Caveat

`deploy.ps1` still exists and performs an ACR-backed container deploy/restart flow against an app named `Lumosradflow`.

That naming does not match the current GitHub Actions targets, so treat it as a separate or legacy manual deployment path unless infrastructure ownership confirms otherwise.

## Validation Checklist

- confirm the relevant GitHub Actions workflow succeeds
- confirm staging or production loads in the browser
- confirm owner, admin, practitioner, MFA, and password-reset flows behave as expected
- confirm dashboard PDF, CSV exports, and settings/report text updates work
