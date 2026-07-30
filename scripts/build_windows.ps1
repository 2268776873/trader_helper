param(
    [string]$Python = "python",
    [string]$Version = "0.1.0"
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
    $warningFile = Join-Path $projectRoot "build\TradeHelper\warn-TradeHelper.txt"
    if (
        (Test-Path -LiteralPath $warningFile) -and
        (Select-String -LiteralPath $warningFile -Pattern "tkinter installation is broken" -Quiet)
    ) {
        throw "PyInstaller excluded tkinter; refusing to publish a non-functional GUI."
    }
    Write-Host "Built: $projectRoot\dist\TradeHelper.exe"
    & "$PSScriptRoot\package_windows_release.ps1" `
        -Version $Version `
        -Executable "$projectRoot\dist\TradeHelper.exe"
}
finally {
    Pop-Location
}
