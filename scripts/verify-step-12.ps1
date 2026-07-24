[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

function Wait-ComposeHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $containerId = (docker compose ps -q $Service).Trim()
        if ($LASTEXITCODE -eq 0 -and $containerId) {
            $status = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $containerId
            if ($LASTEXITCODE -eq 0 -and $status.Trim() -eq "healthy") { return $containerId }
            if ($status.Trim() -eq "unhealthy") { throw "$Service container became unhealthy." }
        }
        Start-Sleep -Seconds 3
    }
    throw "$Service did not become healthy within $TimeoutSeconds seconds."
}

function Assert-HardenedContainer {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$Service
    )

    $hostConfig = docker inspect --format "{{json .HostConfig}}" $ContainerId | ConvertFrom-Json
    Assert-LastExitCode "$Service container inspection failed."
    if (-not $hostConfig.ReadonlyRootfs) { throw "$Service root filesystem is writable." }
    if ($hostConfig.CapDrop -notcontains "ALL") { throw "$Service does not drop all Linux capabilities." }
    if ($hostConfig.SecurityOpt -notcontains "no-new-privileges:true") {
        throw "$Service does not enforce no-new-privileges."
    }
    $user = (docker inspect --format "{{.Config.User}}" $ContainerId).Trim()
    Assert-LastExitCode "$Service runtime-user inspection failed."
    if (-not $user -or $user -eq "0" -or $user -eq "root") { throw "$Service runs as root." }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$reportDirectory = Join-Path $projectRoot "backend\reports\release"
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null

Push-Location $projectRoot
try {
    & (Join-Path $PSScriptRoot "verify-step-11.ps1")

    docker compose --env-file .env config --quiet
    Assert-LastExitCode "Development Compose validation failed."

    $env:PRODUCTION_ENV_FILE = ".env.production.example"
    try {
        docker compose -f compose.production.yaml --env-file .env.production.example config --quiet
        Assert-LastExitCode "Production Compose validation failed."
    }
    finally {
        Remove-Item Env:PRODUCTION_ENV_FILE -ErrorAction SilentlyContinue
    }

    $prometheusVolume = "$projectRoot\ops\prometheus:/etc/prometheus:ro"
    $prometheusArguments = @(
        "run", "--rm",
        "--volume", $prometheusVolume,
        "--entrypoint", "promtool",
        "prom/prometheus:v3.11.3",
        "check", "config", "/etc/prometheus/prometheus.yml"
    )
    & docker @prometheusArguments
    Assert-LastExitCode "Prometheus configuration validation failed."

    docker compose build backend frontend
    Assert-LastExitCode "Release image build failed."
    docker compose up --detach --force-recreate backend frontend
    Assert-LastExitCode "Release containers could not be started."

    $backendContainer = Wait-ComposeHealth -Service "backend"
    $frontendContainer = Wait-ComposeHealth -Service "frontend"
    Assert-HardenedContainer -ContainerId $backendContainer -Service "backend"
    Assert-HardenedContainer -ContainerId $frontendContainer -Service "frontend"

    $frontendResponse = Invoke-WebRequest -Uri "http://127.0.0.1:8080/" -UseBasicParsing -TimeoutSec 10
    if ($frontendResponse.StatusCode -ne 200) { throw "Frontend proxy did not return HTTP 200." }
    foreach ($header in @("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy")) {
        if (-not $frontendResponse.Headers[$header]) { throw "Public proxy is missing $header." }
    }

    $liveResponse = Invoke-WebRequest -Uri "http://127.0.0.1:8080/api/v1/health/live" -UseBasicParsing -TimeoutSec 10
    if ($liveResponse.StatusCode -ne 200 -or -not $liveResponse.Headers["X-Correlation-ID"]) {
        throw "Proxied backend liveness contract failed."
    }

    $metricsStatus = 0
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8080/api/v1/metrics" -UseBasicParsing -TimeoutSec 10 | Out-Null
        $metricsStatus = 200
    }
    catch {
        if ($_.Exception.Response) { $metricsStatus = [int]$_.Exception.Response.StatusCode }
    }
    if ($metricsStatus -ne 404) { throw "Public metrics endpoint was not blocked." }

    $metricsResponse = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/metrics" -UseBasicParsing -TimeoutSec 10
    if ($metricsResponse.StatusCode -ne 200 -or $metricsResponse.Content -notmatch "hotel_http_requests_total") {
        throw "Internal Prometheus metrics contract failed."
    }

    $performanceReport = & (Join-Path $PSScriptRoot "measure-http-performance.ps1")
    $backupManifest = & (Join-Path $PSScriptRoot "backup.ps1")
    $restoreReport = & (Join-Path $PSScriptRoot "restore-rehearsal.ps1") -ManifestPath $backupManifest

    $backendImage = (docker inspect --format "{{.Image}}" $backendContainer).Trim()
    Assert-LastExitCode "Backend image inspection failed."
    $frontendImage = (docker inspect --format "{{.Image}}" $frontendContainer).Trim()
    Assert-LastExitCode "Frontend image inspection failed."
    $releaseEvidence = [ordered]@{
        schema_version = 1
        status = "passed"
        verified_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        step = 12
        backend_container = $backendContainer
        backend_image = $backendImage
        frontend_container = $frontendContainer
        frontend_image = $frontendImage
        prometheus_config = "passed"
        public_metrics_blocked = $true
        security_headers = "passed"
        hardened_containers = "passed"
        performance_report = [System.IO.Path]::GetFileName([string]$performanceReport)
        backup_manifest = [System.IO.Path]::GetFileName([string]$backupManifest)
        restore_report = [System.IO.Path]::GetFileName([string]$restoreReport)
        test_gate = "verify-step-11"
        limitations = @(
            "Public DNS, TLS issuance, and Telegram webhook activation require the selected deployment host.",
            "Performance evidence is a local proxy baseline and excludes public-network and provider latency.",
            "Hotel operations are simulations and are not connected to a real PMS."
        )
    }
    $releaseEvidencePath = Join-Path $reportDirectory "step-12-release-evidence.json"
    $releaseEvidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $releaseEvidencePath -Encoding utf8
}
finally {
    Pop-Location
}

Write-Host "Step 12 verification passed."
