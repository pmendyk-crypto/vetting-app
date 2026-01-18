Render persistent storage and Postgres migration

Problem
-------
On many cloud hosts (including Render), the container filesystem is ephemeral: files written to the application root are lost when the instance is restarted, redeployed, or moved. If your app uses a local SQLite file (hub.db) and an uploads folder inside the project directory, data will appear to "disappear" after deploys or restarts.

Recommended options
-------------------
1) Fast, recommended (short-term): Mount a persistent disk on Render and point the app at it.
   - In Render web service settings, add a Persistent Disk and mount it at `/data`.
   - In the service "Environment" settings, set:
     - `DB_PATH` = `/data/hub.db`
     - `UPLOAD_DIR` = `/data/uploads`
   - Redeploy. The app now writes `hub.db` and uploads to `/data`, which persists across restarts.

2) Production-ready (recommended long-term): Use a managed PostgreSQL database.
   - Provision a Postgres instance (Render Postgres, RDS, etc.).
   - Set `DATABASE_URL` environment variable on the Render service (e.g. `postgres://user:pass@host:5432/dbname`).
   - Optionally: migrate existing SQLite data to Postgres (see migration script in `scripts/`).
   - Advantages: safe for multiple instances, backups, scaling, and long-term reliability.

3) Short-term workaround: export `hub.db` locally before redeploy and re-import afterwards. Not recommended.

Migration script
----------------
A migration helper is included at `scripts/migrate_sqlite_to_postgres.py`. It copies tables from your local `hub.db` to the Postgres instance specified by `DATABASE_URL` environment variable. The script requires `psycopg2-binary` and `SQLAlchemy` installed (already added to `requirements.txt`).

Usage example (local machine)
----------------------------
1. Install updated deps in your virtualenv:

```powershell
pip install -r requirements.txt
```

2. Run the migration (from project root):

```powershell
setx DATABASE_URL "postgres://user:pass@host:5432/dbname"
python scripts\migrate_sqlite_to_postgres.py --sqlite hub.db
```

3. Update Render environment variables and redeploy your service.

Notes
-----
- If you choose the persistent disk option, you do not need to change database code.
- If you choose Postgres, I can implement direct SQLAlchemy usage in the app (instead of sqlite3) so the app runs against Postgres natively. That requires code changes and additional testing.
