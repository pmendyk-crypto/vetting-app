Deployment guide — Heroku, Render, and Cloud Run

This repo is ready to deploy. Below are short instructions for three common hosts.

1) Heroku (quick)
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

2) Render (simple)
- In the Render dashboard, create a new Web Service and connect your GitHub repo.
- Build command: (default)
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Render will build a Docker image or use the Python environment (choose the option you prefer).

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
- For production use, consider running behind a proper process manager or using Gunicorn with Uvicorn workers. For quick deployments the current setup is sufficient.
- Ensure `requirements.txt` lists all runtime dependencies. If you add new packages, update it before deploying.

If you want, I can:
- Push these changes to a new git branch and help you deploy to one of the providers above. 
- Or I can run a Cloud Run build image and attempt a deploy (requires `gcloud` auth).
