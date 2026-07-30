param(
    [string]$Version = "0.1.0",
    [string]$Executable = ".\dist\TradeHelper.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $executablePath = if ([System.IO.Path]::IsPathRooted($Executable)) {
        [System.IO.Path]::GetFullPath($Executable)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Executable))
    }
    if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
        throw "Executable not found: $executablePath"
    }
    $releaseName = "TradeHelper-$Version-windows-x64"
    $releaseRoot = Join-Path $projectRoot "dist\$releaseName"
    $archivePath = Join-Path $projectRoot "dist\$releaseName.zip"
    $checksumPath = "$archivePath.sha256"
    foreach ($path in @($releaseRoot, $archivePath, $checksumPath)) {
        if (Test-Path -LiteralPath $path) {
            throw "Release output already exists; remove it explicitly first: $path"
        }
    }

    New-Item -ItemType Directory -Path $releaseRoot | Out-Null
    New-Item -ItemType Directory -Path "$releaseRoot\docs" | Out-Null
    New-Item -ItemType Directory -Path "$releaseRoot\config" | Out-Null
    New-Item -ItemType Directory -Path "$releaseRoot\templates" | Out-Null
    Copy-Item -LiteralPath $executablePath -Destination "$releaseRoot\TradeHelper.exe"
    Copy-Item -LiteralPath ".\docs\user_manual.md" -Destination "$releaseRoot\docs"
    Copy-Item -LiteralPath ".\docs\privacy_and_risk.md" -Destination "$releaseRoot\docs"
    Copy-Item -LiteralPath ".\docs\client_backup_restore.md" -Destination "$releaseRoot\docs"
    Copy-Item -LiteralPath ".\docs\client_market_collection.md" -Destination "$releaseRoot\docs"
    Copy-Item -LiteralPath ".\config\market_supplement.example.json" -Destination "$releaseRoot\config"
    Copy-Item -LiteralPath ".\outputs\account_template\trade_helper_account_template.xlsx" -Destination "$releaseRoot\templates"

    $manifest = [ordered]@{
        product = "Trade Helper"
        version = $Version
        platform = "windows-x64"
        created_at = [DateTimeOffset]::Now.ToString("o")
        executable_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath "$releaseRoot\TradeHelper.exe").Hash.ToLowerInvariant()
        signed = $false
        notice = "Unsigned test build; local decision support only; no automatic ordering."
    }
    $manifest | ConvertTo-Json | Set-Content -Encoding utf8 "$releaseRoot\release-manifest.json"
    Compress-Archive -LiteralPath $releaseRoot -DestinationPath $archivePath
    & "$PSScriptRoot\verify_windows_release.ps1" -Archive $archivePath
    $archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    "$archiveHash  $releaseName.zip" | Set-Content -Encoding ascii $checksumPath
    Write-Host "Release: $archivePath"
    Write-Host "SHA-256: $archiveHash"
}
finally {
    Pop-Location
}
