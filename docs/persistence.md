Persistent Storage and PostgreSQL Configuration

Problem
-------
On cloud hosts with ephemeral filesystems, local files written to the app root are lost when the instance restarts, redeploys, or moves. If your app uses a local SQLite file (hub.db) and an uploads folder, data will appear to "disappear" after redeploys.

Recommended Solutions
---------------------

1) Azure App Service (RECOMMENDED for this app)

Azure App Service provides persistent storage at `/home/site/wwwroot/` that survives restarts and redeployments.

**Configuration in Azure Portal:**

Set environment variables in **Configuration → Application Settings**:

- `UPLOAD_DIR` = `/home/site/wwwroot/uploads`
- `DATABASE_URL` = Your Azure PostgreSQL connection string
- `APP_SECRET` = Your secure secret key

**Uploads Directory:**

- App automatically creates `/home/site/wwwroot/uploads`
- Files persist across app restarts and deployments
- Can be accessed via Azure Storage if needed

2) Production-Ready: Managed PostgreSQL Database

Use **Azure Database for PostgreSQL** or any PostgreSQL provider.

**Setup:**

1. Create PostgreSQL instance in Azure
2. Set `DATABASE_URL` environment variable:
   ```
   postgresql://username:password@server.postgres.database.azure.com:5432/dbname
   ```
3. App automatically migrates and creates tables on startup
4. No local SQLite database needed

**Advantages:**

- Works across multiple app instances
- Built-in backups and point-in-time restore
- Automatic scaling
- Better for production workloads

Migration from SQLite to PostgreSQL
-----------------------------------

A migration helper is included at `scripts/migrate_sqlite_to_postgres.py`. It copies tables from your local `hub.db` to the PostgreSQL instance.

**Usage:**

```powershell
# Set the target database
setx DATABASE_URL "postgresql://username:password@host:5432/dbname"

# Run migration
python scripts/migrate_sqlite_to_postgres.py --sqlite hub.db
```

The script requires `psycopg2-binary` and `SQLAlchemy` (already included in `requirements.txt`).

Notes
-----

- The app automatically detects PostgreSQL via `DATABASE_URL` and uses it preferentially
- SQLite is still supported for local development
- Azure App Service provides built-in persistent storage for uploads
- For production, always use PostgreSQL instead of SQLite
