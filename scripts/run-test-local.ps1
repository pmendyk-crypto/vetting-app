param(
    [string]$EnvFile = ".env.test.local",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$setupScript = Join-Path $PSScriptRoot "setup-test-env.ps1"

if (-not (Test-Path (Join-Path $repoRoot $EnvFile))) {
    Write-Host "No $EnvFile found. Bootstrapping the test environment first."
    & $setupScript
}

& (Join-Path $PSScriptRoot "run-local.ps1") -EnvFile $EnvFile -HostName $HostName -Port $Port
