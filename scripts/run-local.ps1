param(
    [string]$EnvFile = ".env.local",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (Test-Path $EnvFile) {
    Write-Host "Loading environment from $EnvFile"
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $parts = $line.Split("=", 2)
        if ($parts.Count -ne 2) {
            return
        }

        $name = $parts[0].Trim()
        $value = $parts[1].Trim()

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
} else {
    Write-Host "No $EnvFile file found. Running with current environment."
}

if (-not $env:APP_BASE_URL) {
    $env:APP_BASE_URL = "http://$HostName`:$Port"
}

Write-Host "Starting local app at http://$HostName`:$Port"
if ($Reload) {
    $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--reload", "--host", $HostName, "--port", $Port)
} else {
    $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", $HostName, "--port", $Port)
}

if (Test-Path $venvPython) {
    & $venvPython @uvicornArgs
} else {
    python @uvicornArgs
}
