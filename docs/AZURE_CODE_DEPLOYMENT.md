# Azure Code Deployment

This project deploys to Azure App Service using code publishing rather than containers.
Azure App Service is the only configured staging and production hosting target in this repository.

## Current Environment Flow

1. Work locally in VS Code.
2. Push `develop` to deploy staging.
3. Validate staging on Azure.
4. Merge `develop` into `main`.
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

- `AZUREAPPSERVICE_PUBLISHPROFILE_STAGING`
- `AZUREAPPSERVICE_PUBLISHPROFILE_PRODUCTION`

These secrets must contain the full publish profile XML downloaded from the matching App Service.

## Azure App Configuration

Use Python 3.12 on Linux for both apps.

Recommended app settings for each environment:

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

Environment-specific notes:

- Staging can keep `APP_BASE_URL` on the Azure default hostname.
- Production should keep `APP_BASE_URL` on the Azure hostname until the custom domain is moved.

## Startup Commands

- Staging currently uses: `bash startup.sh`
- Production can use either `bash startup.sh` or a direct Gunicorn command if needed:
  `gunicorn --bind=0.0.0.0:8000 --worker-class uvicorn.workers.UvicornWorker --timeout 600 app.main:app`

## Demo-Ready Checklist

- Confirm both GitHub Actions workflows succeed.
- Confirm staging and production load in the browser.
- Confirm login and key demo flows work.
- Keep the old broken container app out of the demo path.
