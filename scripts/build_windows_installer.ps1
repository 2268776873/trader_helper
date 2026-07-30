param(
    [string]$Version = "0.1.0",
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot "dist\TradeHelper-$Version-windows-x64"
if (-not (Test-Path -LiteralPath "$releaseRoot\TradeHelper.exe" -PathType Leaf)) {
    throw "Verified release folder is missing: $releaseRoot"
}
if (-not $InnoCompiler) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        (Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "Inno Setup 6\ISCC.exe"),
        (Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "Inno Setup 6\ISCC.exe")
    )
    $InnoCompiler = $candidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw "Inno Setup 6 compiler not found; pass -InnoCompiler with ISCC.exe."
}

Push-Location $projectRoot
try {
    & $InnoCompiler "/DMyAppVersion=$Version" ".\installer\TradeHelper.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed."
    }
    $installer = Join-Path $projectRoot "dist\TradeHelper-$Version-windows-x64-setup.exe"
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw "Installer compiler succeeded but output is missing: $installer"
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
    "$hash  $(Split-Path -Leaf $installer)" |
        Set-Content -Encoding ascii "$installer.sha256"
    Write-Host "Installer: $installer"
    Write-Host "SHA-256: $hash"
}
finally {
    Pop-Location
}
