# deploy.ps1 — Build and deploy vetting-app to Azure
# Usage: .\deploy.ps1
# Requirements: Azure CLI (az), Docker Desktop running

$ACR      = "lumosradflow-c9b5crbjbnc4b3dn.azurecr.io"
$IMAGE    = "vetting-app"
$TAG      = "latest"
$APP_NAME = "Lumosradflow"
$RG       = "RadFlow"
$FULL_TAG = "$ACR/${IMAGE}:${TAG}"

Write-Host "`n=== Azure Deploy: $APP_NAME ===" -ForegroundColor Cyan

# 1. Login to ACR
Write-Host "`n[1/3] Logging in to Azure Container Registry..." -ForegroundColor Yellow
az acr login --name LumosRadFlow
if ($LASTEXITCODE -ne 0) { Write-Host "ACR login failed. Run 'az login' first." -ForegroundColor Red; exit 1 }

# 2. Build & push image
Write-Host "`n[2/3] Building and pushing Docker image..." -ForegroundColor Yellow
docker build -t $FULL_TAG .
if ($LASTEXITCODE -ne 0) { Write-Host "Docker build failed." -ForegroundColor Red; exit 1 }

docker push $FULL_TAG
if ($LASTEXITCODE -ne 0) { Write-Host "Docker push failed." -ForegroundColor Red; exit 1 }

# 3. Restart app service
Write-Host "`n[3/3] Restarting App Service to pull new image..." -ForegroundColor Yellow
az webapp restart --name $APP_NAME --resource-group $RG
if ($LASTEXITCODE -ne 0) { Write-Host "App restart failed." -ForegroundColor Red; exit 1 }

Write-Host "`n=== Deploy complete! ===" -ForegroundColor Green
Write-Host "Live URL: https://lumosradflow-h0dggngdg8a2hgbd.ukwest-01.azurewebsites.net`n" -ForegroundColor Green
