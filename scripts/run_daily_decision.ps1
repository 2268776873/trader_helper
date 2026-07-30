param(
    [string]$Python = "python",
    [string]$Database = ".\var\account.db",
    [string]$Config = ".\config\personal_v1.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    & $Python -m trade_helper.cli daily-decision `
        --database $Database `
        --config $Config
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
