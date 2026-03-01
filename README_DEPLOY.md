Deployment guide — Azure, Heroku, and Cloud Run

This repo is ready to deploy. Below are short instructions for three common hosts.

1) Azure App Service (recommended)
- Create an Azure App Service for containers or use App Service with Docker.
- Set environment variables in Azure portal (Configuration → Application Settings):
  - `APP_SECRET`: Your secure secret key
  - `DATABASE_URL`: PostgreSQL connection string
  - `UPLOAD_DIR`: `/home/site/wwwroot/uploads` (persistent storage)
  - `DB_PATH`: Not needed with PostgreSQL
- Deploy via GitHub Actions, Azure CLI, or Docker push to Azure Container Registry:
  ```bash
  az login
  az webapp deployment source config-zip --resource-group YOUR_RG --name YOUR_APP --src deployment.zip
  ```
- App Service includes built-in persistent storage at `/home/site/wwwroot`.

2) Heroku (legacy)
- Create an app and push:
  ```bash
  heroku login
  git init
  heroku create your-app-name
  git add .
  git commit -m "deploy"
  git push heroku main
  ```
- Heroku will use the `Procfile` to run `uvicorn` and the `requirements.txt` for dependencies.

3) Google Cloud Run (container)
- Build the container and push to Google Container Registry, then deploy to Cloud Run.
  ```bash
  gcloud auth login
  gcloud config set project YOUR_PROJECT_ID
  gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/vetting-app
  gcloud run deploy vetting-app --image gcr.io/YOUR_PROJECT_ID/vetting-app --platform managed --region us-central1 --allow-unauthenticated --port 8080
  ```
- Cloud Run expects the container to listen on `$PORT` (Dockerfile sets `PORT=8080` by default).

Notes
- For production use, ensure `requirements.txt` lists all runtime dependencies.
- Use a managed database service (Azure Database for PostgreSQL, Cloud SQL, RDS) rather than SQLite.
- Set strong `APP_SECRET` values in production.
- Uploads directory must be on persistent storage (App Service `/home/site/wwwroot`, or cloud storage).

