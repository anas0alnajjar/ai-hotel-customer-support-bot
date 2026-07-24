[CmdletBinding()]
param(
    [ValidateSet("hashing_test", "sentence_transformers")]
    [string]$Provider = "hashing_test"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Run scripts/setup.ps1 first."
}

Push-Location $projectRoot
try {
    & $python -m hotel_bot.knowledge evaluate --provider $Provider
    if ($LASTEXITCODE -ne 0) { throw "Knowledge retrieval evaluation failed." }
}
finally {
    Pop-Location
}
