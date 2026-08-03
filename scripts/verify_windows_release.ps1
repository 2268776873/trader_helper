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
        "/TradeHelperCLI.exe",
        "/release-manifest.json",
        "/RELEASE_NOTES.md",
        "/docs/user_manual.md",
        "/docs/privacy_and_risk.md",
        "/docs/strategy_replay.md",
        "/config/market_supplement.example.json",
        "/config/personal_v1.json",
        "/config/replay_initial_account.example.json",
        "/config/replay_suite.example.json",
        "/templates/trade_helper_account_template.xlsx",
        "/scripts/register_daily_task.ps1",
        "/scripts/run_daily_pipeline.ps1",
        "/scripts/run_daily_decision.ps1",
        "/scripts/unregister_daily_task.ps1",
        "/data/calendar_2026.csv"
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
