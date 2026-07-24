[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string]$Url,

    [ValidateRange(1, 100)]
    [int]$MaxConnections = 20
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
    & $python -m hotel_bot.telegram $Url --max-connections $MaxConnections
    if ($LASTEXITCODE -ne 0) { throw "Telegram webhook configuration failed." }
}
finally {
    Pop-Location
}
