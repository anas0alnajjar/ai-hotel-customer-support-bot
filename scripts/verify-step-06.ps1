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
    & $python -m hotel_bot.knowledge evaluate --provider hashing_test
    if ($LASTEXITCODE -ne 0) { throw "Knowledge evaluation failed." }

    & $python -m ruff check backend
    if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed." }

    & $python -m ruff format --check backend
    if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed." }

    & $python -m mypy backend/src backend/tests
    if ($LASTEXITCODE -ne 0) { throw "Mypy failed." }

    & $python -m alembic -c backend/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed." }

    & $python -m alembic -c backend/alembic.ini check
    if ($LASTEXITCODE -ne 0) { throw "Schema drift detected." }

    & $python -m hotel_bot.knowledge seed
    if ($LASTEXITCODE -ne 0) { throw "Knowledge seed failed." }

    $env:RUN_MYSQL_INTEGRATION = "1"
    & $python -m pytest backend/tests
    if ($LASTEXITCODE -ne 0) { throw "Pytest failed." }

    docker compose --env-file .env config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose validation failed." }
}
finally {
    Remove-Item Env:RUN_MYSQL_INTEGRATION -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host "Step 6 verification passed."
