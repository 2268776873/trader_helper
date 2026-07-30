param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    & $Python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) {
        throw "Automated tests failed; package was not built."
    }
    & $Python -m PyInstaller --noconfirm --clean .\TradeHelper.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
    Write-Host "Built: $projectRoot\dist\TradeHelper.exe"
}
finally {
    Pop-Location
}
