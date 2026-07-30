param(
    [string]$Python = "python",
    [string]$Version = "0.1.0",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    if (-not $SkipTests) {
        & $Python -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) {
            throw "Automated tests failed; package was not built."
        }
    }
    & $Python -m PyInstaller --noconfirm --clean .\TradeHelper.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
    & $Python -m PyInstaller --noconfirm --clean .\TradeHelperCLI.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller CLI build failed."
    }
    $warningFile = Join-Path $projectRoot "build\TradeHelper\warn-TradeHelper.txt"
    if (
        (Test-Path -LiteralPath $warningFile) -and
        (Select-String -LiteralPath $warningFile -Pattern "tkinter installation is broken" -Quiet)
    ) {
        throw "PyInstaller excluded tkinter; refusing to publish a non-functional GUI."
    }
    Write-Host "Built: $projectRoot\dist\TradeHelper.exe"
    Write-Host "Built: $projectRoot\dist\TradeHelperCLI.exe"
    & "$PSScriptRoot\package_windows_release.ps1" `
        -Version $Version `
        -Executable "$projectRoot\dist\TradeHelper.exe" `
        -CliExecutable "$projectRoot\dist\TradeHelperCLI.exe"
}
finally {
    Pop-Location
}
