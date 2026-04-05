# Deployment

## Current Branch-To-Environment Workflow

The repo's active GitHub Actions deployment path is:

- push to `develop` -> deploy staging via `.github/workflows/deploy-staging.yml`
  - Azure Web App: `lumosradflow-staging`
- push to `main` -> deploy production via `.github/workflows/deploy-production.yml`
  - Azure Web App: `lumosradflow-prod`

Both workflows currently:

1. check out the repo
2. set up Python 3.12
3. run `pip install -r requirements.txt`
4. deploy the repo package with `azure/webapps-deploy@v3`

## Current Local-Then-Deploy Flow

1. Work from `develop`.
2. Install dependencies:
   `python -m pip install --upgrade pip`
   `pip install -r requirements.txt`
3. Run locally:
   `.\scripts\run-local.ps1 -Reload`
4. Run the isolated manual test environment if needed:
   `.\scripts\setup-test-env.ps1`
   `.\scripts\run-test-local.ps1`
5. Push `develop` and validate the staging site.
6. Promote to `main` only after staging validation.

## Runtime Expectations

The app currently starts as ASGI app `app.main:app`.

Repo startup/runtime assets:

- `scripts/run-local.ps1` runs `uvicorn app.main:app`
- `Dockerfile` uses:
  `uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`
- `startup.sh` uses Gunicorn with Uvicorn workers:
  `gunicorn --worker-class uvicorn.workers.UvicornWorker app.main:app`

## Environment Settings To Provide

At minimum, deployed environments should define:

- `APP_SECRET`
- `APP_BASE_URL`
- either `DATABASE_URL` for PostgreSQL or `DB_PATH` for SQLite-style storage
- `UPLOAD_DIR` when using local filesystem uploads

Optional but currently supported:

- `AZURE_STORAGE_CONNECTION_STRING`
- SMTP settings for password reset and practitioner notifications
- `IREFER_API_KEY`

The tracked env examples also include:

- `REFERRAL_FILE_TTL_DAYS`
- `CASE_RECORD_TTL_DAYS`
- `REFERRAL_BLOB_CONTAINER`
- `ALLOW_DIAGNOSTIC_ENDPOINT`

## Manual Azure Deploy Script

The repo also contains `deploy.ps1`, which:

1. logs into Azure Container Registry
2. builds and pushes a Docker image
3. restarts an Azure App Service named `Lumosradflow`

That manual script does not match the GitHub Actions app names (`lumosradflow-staging` and `lumosradflow-prod`), so from code alone it looks like a separate or older manual deployment path. Use it only if your infrastructure process still relies on that app service/container route.
