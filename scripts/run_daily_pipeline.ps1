param(
    [string]$Python = "python",
    [string]$Database = ".\var\account.db",
    [string]$Config = ".\config\personal_v1.json",
    [string]$Supplement = ".\var\today-market.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    if (-not (Test-Path -LiteralPath $Supplement -PathType Leaf)) {
        throw "Market supplement file not found: $Supplement"
    }

    & $Python -m trade_helper.cli market-collect $Supplement `
        --database $Database `
        --config $Config
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $Python -m trade_helper.cli daily-decision `
        --database $Database `
        --config $Config
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
