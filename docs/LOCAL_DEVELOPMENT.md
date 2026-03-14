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

## Normal Workflow

1. Build and test locally first.
2. Commit and push to `develop`.
3. Validate on staging.
4. Merge to `main` only when ready for production.
