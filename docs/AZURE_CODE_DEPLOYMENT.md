# Azure Code Deployment

This project is set up to deploy to Azure App Service using code publishing instead of containers.

## Target Flow

1. Work locally in VS Code.
2. Push `develop` to deploy staging.
3. Validate staging.
4. Merge or push to `main` to deploy production.

## Repo Changes

- `startup.sh` runs the FastAPI app with Gunicorn/Uvicorn.
- `requirements.txt` includes `gunicorn`.
- `.github/workflows/deploy-staging.yml` deploys `develop` to staging.
- `.github/workflows/deploy-production.yml` deploys `main` to production.

## Azure App Service Settings

Set these for both App Services:

- Runtime stack: `Python 3.12`
- Startup command: `bash startup.sh`
- App setting: `SCM_DO_BUILD_DURING_DEPLOYMENT=true`
- App setting: `ENABLE_ORYX_BUILD=true`

Set your normal app settings separately for staging and production:

- `APP_SECRET`
- `APP_BASE_URL`
- `DATABASE_URL`
- `SMTP_*`
- storage settings
- API keys

## GitHub Secrets

Add these repository secrets:

- `AZUREAPPSERVICE_PUBLISHPROFILE_STAGING`
- `AZUREAPPSERVICE_PUBLISHPROFILE_PRODUCTION`

Use the publish profile downloaded from each App Service.
