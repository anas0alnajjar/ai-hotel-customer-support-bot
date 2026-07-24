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
    & $python -m alembic -c backend/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed." }

    & $python -m hotel_bot.knowledge seed
    if ($LASTEXITCODE -ne 0) { throw "Knowledge seed failed." }
}
finally {
    Pop-Location
}
