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
    $supplementPath = if ($Supplement) {
        Resolve-ProjectPath $Supplement
    } else {
        Join-Path $env:LOCALAPPDATA "TradeHelper\today-market.json"
    }
    if (-not (Test-Path -LiteralPath $cliPath -PathType Leaf)) {
        throw "Trade Helper CLI not found: $cliPath"
    }
    if (-not (Test-Path -LiteralPath $supplementPath -PathType Leaf)) {
        throw "Market supplement file not found: $supplementPath"
    }

    & $cliPath market-collect $supplementPath `
        --database $databasePath `
        --config $configPath
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
