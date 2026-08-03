param(
    [string]$CliExecutable = ".\TradeHelperCLI.exe",
    [string]$Database = "",
    [string]$Config = ".\config\personal_v1.json",
    [string]$Supplement = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
function Resolve-ProjectPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Value))
}
Push-Location $projectRoot
try {
    $cliPath = Resolve-ProjectPath $CliExecutable
    $databasePath = if ($Database) {
        Resolve-ProjectPath $Database
    } else {
        Join-Path $env:LOCALAPPDATA "TradeHelper\account.db"
    }
    $configPath = Resolve-ProjectPath $Config
    $supplementPath = if ($Supplement) { Resolve-ProjectPath $Supplement } else { $null }
    if (-not (Test-Path -LiteralPath $cliPath -PathType Leaf)) {
        throw "Trade Helper CLI not found: $cliPath"
    }
    $calendarCsv = Join-Path $projectRoot "data\calendar_2026.csv"
    if (Test-Path -LiteralPath $calendarCsv -PathType Leaf) {
        & $cliPath calendar-import $calendarCsv `
            --database $databasePath `
            --source SSE-2026 `
            --if-missing-date (Get-Date -Format "yyyy-MM-dd")
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "calendar auto-seed failed; continuing with existing calendar data"
        }
    }
    if ($supplementPath) {
        if (-not (Test-Path -LiteralPath $supplementPath -PathType Leaf)) {
            throw "Explicit market fallback file not found: $supplementPath"
        }
        & $cliPath market-collect $supplementPath `
            --database $databasePath `
            --config $configPath
    }
    else {
        & $cliPath market-collect `
            --database $databasePath `
            --config $configPath
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $cliPath daily-decision `
        --database $databasePath `
        --config $configPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
