param(
    [string]$Python = "python",
    [string]$Database = ".\var\account.db",
    [string]$Config = ".\config\personal_v1.json",
    [string]$Supplement = ".\var\today-market.json",
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
$databasePath = Resolve-ProjectPath $Database
$configPath = Resolve-ProjectPath $Config
$supplementPath = Resolve-ProjectPath $Supplement
$pythonPath = if ([System.IO.Path]::IsPathRooted($Python)) {
    $Python
}
else {
    (Get-Command $Python -ErrorAction Stop).Source
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$runner`"",
    "-Python", "`"$pythonPath`"",
    "-Database", "`"$databasePath`"",
    "-Config", "`"$configPath`"",
    "-Supplement", "`"$supplementPath`""
) -join " "

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
Write-Host "Update the supplement file before the task starts: $supplementPath"
