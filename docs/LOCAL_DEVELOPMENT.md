# Local Development

## Daily Start

1. Switch to the working branch:
   `git checkout develop`
2. Pull the latest staging branch:
   `git pull origin develop`
3. Activate the virtual environment:
   `.venv\Scripts\Activate.ps1`
4. Create a local environment file once:
   `Copy-Item .env.local.example .env.local`
5. Start the app:
   `.\scripts\run-local.ps1`

Then open:

- `http://127.0.0.1:8000`

## Local Environment File

Use `.env.local` for local-only settings. It is ignored by Git.

Minimal local values:

- `APP_BASE_URL=http://127.0.0.1:8000`
- `APP_SECRET=local-dev-secret-change-me`
- `DB_PATH=hub.local.db`

By default, the app can run locally with SQLite.

## Optional Local Integrations

- Set `DATABASE_URL` if you want to test against PostgreSQL locally.
- Set `AZURE_STORAGE_CONNECTION_STRING` if you want to test Azure Blob Storage locally.
- Leave SMTP variables empty unless you are testing email flows.

## Local Test Environment

Use the isolated test setup when you want to try changes without touching `hub.local.db`.

1. Bootstrap the test environment:
   `.\scripts\setup-test-env.ps1`
2. Start the app in test mode:
   `.\scripts\run-test-local.ps1`

This creates or reuses:

- `.env.test.local`
- `hub.test.db`
- `uploads-test`

Defaults for the test environment:

- `APP_BASE_URL=http://127.0.0.1:8001`
- `DB_PATH=hub.test.db`
- `UPLOAD_DIR=uploads-test`

The test runner starts without hot reload so it stays stable while you manually test against the isolated database on port `8001`.

Use `.\scripts\setup-test-env.ps1 -Force` if you want to refresh the test database and env file from the tracked template.

## Normal Workflow

1. Build and test locally first.
2. Commit and push to `develop`.
3. Validate on staging.
4. Merge to `main` only when ready for production.
