[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectRoot ".env"
$environmentExample = Join-Path $projectRoot ".env.example"
$virtualEnvironment = Join-Path $projectRoot ".venv"
$python = Join-Path $virtualEnvironment "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    Copy-Item -LiteralPath $environmentExample -Destination $environmentFile
    Write-Host "Created .env from .env.example. Replace GEMINI_API_KEY before the Gemini step."
}

if (-not (Test-Path -LiteralPath $python)) {
    py -3.12 -m venv $virtualEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Python virtual environment."
    }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}

& $python -m pip install --editable "$projectRoot\backend[dev]"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install backend dependencies."
}

Write-Host "Local environment is ready."
