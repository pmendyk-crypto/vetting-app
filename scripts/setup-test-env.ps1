param(
    [string]$SourceDb = "hub.local.db",
    [string]$TestDb = "hub.test.db",
    [string]$TemplateEnvFile = ".env.test.local.example",
    [string]$EnvFile = ".env.test.local",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "==> $Message"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDbPath = Join-Path $repoRoot $SourceDb
$fallbackDbPath = Join-Path $repoRoot "hub.db"
$testDbPath = Join-Path $repoRoot $TestDb
$templateEnvPath = Join-Path $repoRoot $TemplateEnvFile
$envPath = Join-Path $repoRoot $EnvFile
$testUploadDir = Join-Path $repoRoot "uploads-test"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Missing virtual environment at .venv. Create it first, for example: py -m venv .venv"
}

if (-not (Test-Path $sourceDbPath)) {
    if (Test-Path $fallbackDbPath) {
        $sourceDbPath = $fallbackDbPath
    } else {
        throw "Could not find source database '$SourceDb' or fallback 'hub.db'."
    }
}

if (-not (Test-Path $templateEnvPath)) {
    throw "Missing template env file '$TemplateEnvFile'."
}

Write-Step "Checking Python dependencies"
& $venvPython -c "import fastapi, uvicorn, sqlalchemy; print('Python env looks good')"

Write-Step "Ensuring uploads-test exists"
New-Item -ItemType Directory -Path $testUploadDir -Force | Out-Null

if ((Test-Path $testDbPath) -and -not $Force) {
    Write-Step "Keeping existing $TestDb"
} else {
    Write-Step "Creating fresh $TestDb from $(Split-Path $sourceDbPath -Leaf)"
    Copy-Item -LiteralPath $sourceDbPath -Destination $testDbPath -Force
}

if ((Test-Path $envPath) -and -not $Force) {
    Write-Step "Keeping existing $EnvFile"
} else {
    Write-Step "Creating $EnvFile from template"
    Copy-Item -LiteralPath $templateEnvPath -Destination $envPath -Force
}

Write-Host ""
Write-Host "Local test environment is ready."
Write-Host "  Env file : $EnvFile"
Write-Host "  Test DB  : $TestDb"
Write-Host "  Uploads  : uploads-test"
Write-Host ""
Write-Host "Start it with:"
Write-Host "  .\scripts\run-test-local.ps1"
