[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Run scripts/setup.ps1 first."
}

Push-Location $projectRoot
try {
    & $python -m ruff check backend
    if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed." }

    & $python -m ruff format --check backend
    if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed." }

    & $python -m mypy backend/src backend/tests
    if ($LASTEXITCODE -ne 0) { throw "Mypy failed." }

    & $python -m pytest backend/tests
    if ($LASTEXITCODE -ne 0) { throw "Pytest failed." }

    docker compose --env-file .env config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose validation failed." }
}
finally {
    Pop-Location
}

Write-Host "Step 1 verification passed."
