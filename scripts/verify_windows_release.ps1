param(
    [Parameter(Mandatory = $true)]
    [string]$Archive
)

$ErrorActionPreference = "Stop"
$archivePath = [System.IO.Path]::GetFullPath($Archive)
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "Release archive not found: $archivePath"
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $entries = @($zip.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
    $requiredSuffixes = @(
        "/TradeHelper.exe",
        "/release-manifest.json",
        "/docs/user_manual.md",
        "/docs/privacy_and_risk.md",
        "/config/market_supplement.example.json",
        "/templates/trade_helper_account_template.xlsx"
    )
    foreach ($suffix in $requiredSuffixes) {
        if (-not ($entries | Where-Object { $_.EndsWith($suffix) })) {
            throw "Release archive is missing required entry: $suffix"
        }
    }
    $forbidden = @(
        $entries | Where-Object {
            $_ -match "(^|/)var/" -or
            $_ -match "\.(db|sqlite|thbackup)$" -or
            $_ -match "(^|/)account\.xlsx$"
        }
    )
    if ($forbidden.Count -gt 0) {
        throw "Release archive contains private or local data: $($forbidden -join ', ')"
    }
    Write-Host "Release verification passed: $($entries.Count) entries"
}
finally {
    $zip.Dispose()
}
