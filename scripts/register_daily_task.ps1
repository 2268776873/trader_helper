param(
    [string]$CliExecutable = ".\TradeHelperCLI.exe",
    [string]$Database = "",
    [string]$Config = ".\config\personal_v1.json",
    [string]$Supplement = "",
    [string]$TaskName = "TradeHelper-DailyDecision"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run_daily_pipeline.ps1"
function Resolve-ProjectPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Value))
}
$databasePath = if ($Database) {
    Resolve-ProjectPath $Database
} else {
    Join-Path $env:LOCALAPPDATA "TradeHelper\account.db"
}
$configPath = Resolve-ProjectPath $Config
$supplementPath = if ($Supplement) { Resolve-ProjectPath $Supplement } else { $null }
$cliPath = Resolve-ProjectPath $CliExecutable
if (-not (Test-Path -LiteralPath $cliPath -PathType Leaf)) {
    throw "Trade Helper CLI not found: $cliPath"
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$runner`"",
    "-CliExecutable", "`"$cliPath`"",
    "-Database", "`"$databasePath`"",
    "-Config", "`"$configPath`""
) -join " "
if ($supplementPath) {
    $arguments += " -Supplement `"$supplementPath`""
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "14:40"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Trade Helper V1 audited market collection and daily decision pipeline." `
    -Force | Out-Null

Write-Host "Registered task: $TaskName"
Write-Host "The task triggers on weekdays at 14:40; explicit A-share calendar data still gates decisions."
Write-Host "Market quotes and ETF reference values are collected automatically."
if ($supplementPath) {
    Write-Host "Explicit fallback file: $supplementPath"
}
