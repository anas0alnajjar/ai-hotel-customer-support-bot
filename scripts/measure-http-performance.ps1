[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [ValidateRange(20, 10000)]
    [int]$Samples = 100,
    [ValidateRange(1, 60000)]
    [int]$P95TargetMilliseconds = 2000,
    [string]$ReportDirectory = "backend/reports/release"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Percentile {
    param(
        [Parameter(Mandatory = $true)]
        [double[]]$Values,
        [Parameter(Mandatory = $true)]
        [double]$Percentile
    )

    $sorted = @($Values | Sort-Object)
    $index = [Math]::Ceiling(($Percentile / 100.0) * $sorted.Count) - 1
    $index = [Math]::Max(0, [Math]::Min($index, $sorted.Count - 1))
    return [double]$sorted[$index]
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$reportPath = if ([System.IO.Path]::IsPathRooted($ReportDirectory)) {
    $ReportDirectory
}
else {
    Join-Path $projectRoot $ReportDirectory
}
New-Item -ItemType Directory -Path $reportPath -Force | Out-Null
$reportPath = (Resolve-Path -LiteralPath $reportPath).Path
$uri = "$($BaseUrl.TrimEnd('/'))/api/v1/health/live"

for ($warmup = 0; $warmup -lt 5; $warmup++) {
    Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 10 | Out-Null
}

$durations = New-Object System.Collections.Generic.List[double]
$correlationFailures = 0
for ($sample = 0; $sample -lt $Samples; $sample++) {
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 10
    $stopwatch.Stop()
    if ($response.StatusCode -ne 200) { throw "Performance sample returned HTTP $($response.StatusCode)." }
    if (-not $response.Headers["X-Correlation-ID"]) { $correlationFailures++ }
    $durations.Add($stopwatch.Elapsed.TotalMilliseconds)
}

$values = $durations.ToArray()
$p95 = Get-Percentile -Values $values -Percentile 95
$report = [ordered]@{
    schema_version = 1
    status = if ($p95 -le $P95TargetMilliseconds -and $correlationFailures -eq 0) { "passed" } else { "failed" }
    measured_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    scope = "local_reverse_proxy_liveness"
    endpoint = $uri
    samples = $Samples
    warmup_samples = 5
    sequential_requests = $true
    min_ms = [Math]::Round(($values | Measure-Object -Minimum).Minimum, 3)
    mean_ms = [Math]::Round(($values | Measure-Object -Average).Average, 3)
    p50_ms = [Math]::Round((Get-Percentile -Values $values -Percentile 50), 3)
    p95_ms = [Math]::Round($p95, 3)
    p99_ms = [Math]::Round((Get-Percentile -Values $values -Percentile 99), 3)
    max_ms = [Math]::Round(($values | Measure-Object -Maximum).Maximum, 3)
    p95_target_ms = $P95TargetMilliseconds
    missing_correlation_ids = $correlationFailures
    limitation = "This is a local reverse-proxy baseline, not public-network, Telegram, or Gemini latency."
}
$reportFile = Join-Path $reportPath "http-performance-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')).json"
$report | ConvertTo-Json | Set-Content -LiteralPath $reportFile -Encoding utf8
if ($report.status -ne "passed") { throw "HTTP performance gate failed. Report: $reportFile" }

Write-Output $reportFile
