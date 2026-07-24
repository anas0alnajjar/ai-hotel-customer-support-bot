[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [string]$ReportDirectory = "backend/reports/release"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-FixedTimeAsciiEqual {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Left,
        [Parameter(Mandatory = $true)]
        [string]$Right
    )

    $leftBytes = [System.Text.Encoding]::ASCII.GetBytes($Left)
    $rightBytes = [System.Text.Encoding]::ASCII.GetBytes($Right)
    $difference = $leftBytes.Length -bxor $rightBytes.Length
    $length = [Math]::Max($leftBytes.Length, $rightBytes.Length)
    for ($index = 0; $index -lt $length; $index++) {
        $leftByte = if ($index -lt $leftBytes.Length) { $leftBytes[$index] } else { 0 }
        $rightByte = if ($index -lt $rightBytes.Length) { $rightBytes[$index] } else { 0 }
        $difference = $difference -bor ($leftByte -bxor $rightByte)
    }

    return $difference -eq 0
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedManifest = (Resolve-Path -LiteralPath $ManifestPath).Path
$manifest = Get-Content -LiteralPath $resolvedManifest -Raw -Encoding utf8 | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.format -ne "mysql-logical-sql") {
    throw "Unsupported backup manifest."
}
if ([System.IO.Path]::GetFileName([string]$manifest.backup_file) -ne $manifest.backup_file) {
    throw "Backup filename must not contain a path."
}

$backupPath = Join-Path (Split-Path -Parent $resolvedManifest) $manifest.backup_file
$backupPath = (Resolve-Path -LiteralPath $backupPath).Path
$actualHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not (Test-FixedTimeAsciiEqual -Left $actualHash -Right ([string]$manifest.sha256))) {
    throw "Backup checksum does not match the manifest."
}

$reportPath = if ([System.IO.Path]::IsPathRooted($ReportDirectory)) {
    $ReportDirectory
}
else {
    Join-Path $projectRoot $ReportDirectory
}
New-Item -ItemType Directory -Path $reportPath -Force | Out-Null
$reportPath = (Resolve-Path -LiteralPath $reportPath).Path

$suffix = "{0}-{1}" -f (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss"), $PID
$containerName = "hotel-bot-restore-$suffix"
$databaseName = "hotel_bot_restore"
$rootPassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$startedAt = (Get-Date).ToUniversalTime()

try {
    $runArguments = @(
        "run",
        "--detach",
        "--rm",
        "--name", $containerName,
        "--env", "MYSQL_ROOT_PASSWORD=$rootPassword",
        "--env", "MYSQL_DATABASE=$databaseName",
        "mysql:8.4",
        "--character-set-server=utf8mb4",
        "--collation-server=utf8mb4_0900_ai_ci"
    )
    & docker @runArguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not start isolated restore container." }

    $ready = $false
    $pingArguments = @(
        "exec",
        "--env", "MYSQL_PWD=$rootPassword",
        $containerName,
        "mysql",
        "--user=root",
        "--batch",
        "--skip-column-names",
        "--execute=SELECT 1",
        $databaseName
    )
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 2
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "SilentlyContinue"
            $pingResult = & docker @pingArguments 2>$null
            $pingExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($pingExitCode -eq 0 -and $pingResult.Trim() -eq "1") {
            $ready = $true
            break
        }
    }
    if (-not $ready) { throw "Isolated MySQL did not become ready." }

    docker cp $backupPath "${containerName}:/tmp/restore.sql" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not copy backup into restore container." }

    $restoreArguments = @(
        "exec",
        "--env", "MYSQL_PWD=$rootPassword",
        $containerName,
        "mysql",
        "--user=root",
        "--execute=source /tmp/restore.sql",
        $databaseName
    )
    & docker @restoreArguments
    if ($LASTEXITCODE -ne 0) { throw "Restore command failed." }

    $validationQuery = 'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE(); SELECT COUNT(*) FROM alembic_version; SELECT COUNT(*) FROM knowledge_documents; SELECT COUNT(*) FROM conversations;'
    $validationArguments = @(
        "exec",
        "--env", "MYSQL_PWD=$rootPassword",
        $containerName,
        "mysql",
        "--user=root",
        "--batch",
        "--skip-column-names",
        "--execute=$validationQuery",
        $databaseName
    )
    $validationRows = @(& docker @validationArguments)
    if ($LASTEXITCODE -ne 0 -or $validationRows.Count -ne 4) {
        throw "Restore validation queries failed."
    }
    $tableCount = [int]$validationRows[0].Trim()
    $alembicRows = [int]$validationRows[1].Trim()
    $knowledgeRows = [int]$validationRows[2].Trim()
    $conversationRows = [int]$validationRows[3].Trim()
    if ($tableCount -ne [int]$manifest.source_table_count -or $alembicRows -ne 1) {
        throw "Restored schema does not match the backup manifest."
    }

    $finishedAt = (Get-Date).ToUniversalTime()
    $report = [ordered]@{
        schema_version = 1
        status = "passed"
        started_at_utc = $startedAt.ToString("o")
        finished_at_utc = $finishedAt.ToString("o")
        duration_seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
        backup_manifest = [System.IO.Path]::GetFileName($resolvedManifest)
        backup_sha256 = $actualHash
        restored_table_count = $tableCount
        alembic_version_rows = $alembicRows
        knowledge_document_rows = $knowledgeRows
        conversation_rows = $conversationRows
        isolation = "temporary_container_without_host_port_or_project_volume"
        authoritative_restore = "mysql"
        derived_recovery = "faiss_rebuild_required"
    }
    $reportFile = Join-Path $reportPath "restore-rehearsal-$suffix.json"
    $report | ConvertTo-Json | Set-Content -LiteralPath $reportFile -Encoding utf8
    Write-Output $reportFile
}
finally {
    docker rm --force $containerName 2>$null | Out-Null
}
