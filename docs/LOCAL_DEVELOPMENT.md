# Local Development

## Branch Workflow

The current repo automation is wired like this:

- work locally from `develop`
- push `develop` to trigger staging deployment
- validate on staging
- merge or fast-forward into `main` only when ready for production
- push `main` to trigger production deployment

This is backed by:

- `.github/workflows/deploy-staging.yml` on `develop`
- `.github/workflows/deploy-production.yml` on `main`

## Local Run

1. Check out and update the working branch:
   `git checkout develop`
   `git pull origin develop`
2. Create and activate the virtual environment if needed:
   `py -m venv .venv`
   `.venv\Scripts\Activate.ps1`
3. Install dependencies:
   `python -m pip install --upgrade pip`
   `pip install -r requirements.txt`
4. Create the local env file once:
   `Copy-Item .env.local.example .env.local`
5. Start the app:
   `.\scripts\run-local.ps1 -Reload`

Default local URL:

- `http://127.0.0.1:8000`

`run-local.ps1` loads env vars from the selected env file, sets `APP_BASE_URL` if missing, and runs `uvicorn app.main:app`.

## Local Environment Values

Tracked examples currently define:

- `.env.local.example`
  - `APP_ENV=development`
  - `APP_BASE_URL=http://127.0.0.1:8000`
  - `APP_SECRET=local-dev-secret-change-me`
  - `DB_PATH=hub.local.db`
  - `UPLOAD_DIR=uploads`
- `.env.test.local.example`
  - `APP_BASE_URL=http://127.0.0.1:8001`
  - `DB_PATH=hub.test.db`
  - `UPLOAD_DIR=uploads-test`

Optional integrations from the env templates:

- `DATABASE_URL` for PostgreSQL
- `AZURE_STORAGE_CONNECTION_STRING` for blob-backed uploads
- SMTP settings for password reset and practitioner notification emails
- `IREFER_API_KEY` for iRefer lookup
- `OWNER_ADMIN_USERNAME`, `OWNER_ADMIN_EMAIL`, `OWNER_ADMIN_PASSWORD` for the canonical owner account

## Isolated Test Run

The current repo supports an isolated manual-test environment rather than a dedicated automated test harness.

1. Bootstrap the test environment:
   `.\scripts\setup-test-env.ps1`
2. Start the isolated app:
   `.\scripts\run-test-local.ps1`

What this creates or reuses:

- `.env.test.local`
- `hub.test.db`
- `uploads-test`

Default isolated URL:

- `http://127.0.0.1:8001`

Use `.\scripts\setup-test-env.ps1 -Force` to recreate the test DB and env file from the tracked template.

## Current Testing Reality

What can be verified from the repo today:

- local manual testing is a first-class path via `setup-test-env.ps1` and `run-test-local.ps1`
- there is no tracked `pytest` dependency in `requirements.txt`
- there are ad hoc test scripts and `tests/` utilities, but no single documented automated test command is wired into the repo scripts

So the safest current workflow is:

1. run locally on `.env.local`
2. verify risky changes again on the isolated test environment
3. push to `develop`
4. validate staging before promoting to `main`

## Local Auth And MFA Notes

Current auth behavior you should expect when testing locally:

- `/login` performs the credential step
- users with active MFA are redirected to `/login/mfa`
- users marked `mfa_required` but not yet enrolled are redirected to `/account?msg=mfa_required`
- admin access is blocked until required MFA enrollment is completed

That makes the account page part of normal local verification whenever you change auth, role management, or admin-user setup flows.

## Keeping Logins Aligned Across Environments

To keep the owner login aligned across local, staging, and production, use the same canonical owner account values in each environment and seed them deliberately instead of relying on ad hoc DB state.

Canonical owner variables:

- `OWNER_ADMIN_USERNAME`
- `OWNER_ADMIN_EMAIL`
- `OWNER_ADMIN_PASSWORD`

Seed command:

`.\.venv\Scripts\python.exe .\scripts\seed_owner_account.py --env-file .env.local`

Notes:

- local SQLite bootstrapping still uses these env vars automatically when present
- for the isolated test DB, use:
  `.\.venv\Scripts\python.exe .\scripts\seed_owner_account.py --env-file .env.test.local`
- staging and production should run the same seed script against their configured `DATABASE_URL`
- do not rely on the older `create_superadmin.py` or `init_azure_superadmin.py` flows for environment setup
