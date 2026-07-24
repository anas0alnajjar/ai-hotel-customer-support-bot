[CmdletBinding()]
param(
    [string]$OutputDirectory = "backups"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$outputPath = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
}
else {
    Join-Path $projectRoot $OutputDirectory
}

New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$outputPath = (Resolve-Path -LiteralPath $outputPath).Path

Push-Location $projectRoot
try {
    $container = (docker compose ps -q mysql).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $container) {
        throw "The Compose MySQL container is not available."
    }

    $running = docker inspect --format "{{.State.Running}}" $container
    if ($LASTEXITCODE -ne 0 -or $running -ne "true") {
        throw "The Compose MySQL container is not running."
    }

    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $baseName = "hotel-bot-$timestamp"
    $backupPath = Join-Path $outputPath "$baseName.sql"
    $manifestPath = Join-Path $outputPath "$baseName.manifest.json"
    $containerDump = "/tmp/$baseName.sql"
    $dumpCommand = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --user=root --single-transaction --quick --routines --triggers --events --hex-blob --set-gtid-purged=OFF --no-tablespaces "$MYSQL_DATABASE" > "$1"'

    try {
        $dumpArguments = @("exec", $container, "sh", "-c", $dumpCommand, "sh", $containerDump)
        & docker @dumpArguments
        if ($LASTEXITCODE -ne 0) { throw "mysqldump failed." }

        docker exec $container test -s $containerDump
        if ($LASTEXITCODE -ne 0) { throw "The generated database dump is empty." }

        docker cp "${container}:$containerDump" $backupPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not copy the dump from MySQL." }
    }
    finally {
        docker exec $container rm -f $containerDump 2>$null | Out-Null
    }

    $tableQuery = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --skip-column-names --execute=''SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()'' "$MYSQL_DATABASE"'
    $tableArguments = @("exec", $container, "sh", "-c", $tableQuery)
    $tableCountText = & docker @tableArguments
    if ($LASTEXITCODE -ne 0) { throw "Could not count source tables." }
    $tableCount = [int]$tableCountText.Trim()

    $file = Get-Item -LiteralPath $backupPath
    if ($file.Length -le 0) { throw "The copied backup is empty." }
    $hash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        schema_version = 1
        format = "mysql-logical-sql"
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        backup_file = $file.Name
        sha256 = $hash
        size_bytes = $file.Length
        source_table_count = $tableCount
        faiss_recovery = "rebuild_from_approved_knowledge_revisions"
    }
    $manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8

    Write-Output $manifestPath
}
finally {
    Pop-Location
}
