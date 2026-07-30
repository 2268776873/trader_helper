param(
    [string]$Executable = ".\dist\TradeHelper.exe",
    [int]$TimeoutSeconds = 20,
    [switch]$AllowVisibleLaunch
)

$ErrorActionPreference = "Stop"
if (-not $AllowVisibleLaunch) {
    throw (
        "This test opens a visible Trade Helper window. " +
        "Re-run with -AllowVisibleLaunch only after the user has been warned."
    )
}
$executablePath = [System.IO.Path]::GetFullPath($Executable)
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "Executable not found: $executablePath"
}
$startedAt = Get-Date
$previousDatabase = $env:TRADE_HELPER_DB
$smokeDatabase = Join-Path $env:TEMP (
    "TradeHelper-smoke-" + [Guid]::NewGuid().ToString("N") + ".db"
)
$launched = @()
try {
    $env:TRADE_HELPER_DB = $smokeDatabase
    $parent = Start-Process -FilePath $executablePath -PassThru
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $windowProcess = $null
    while ((Get-Date) -lt $deadline -and -not $windowProcess) {
        Start-Sleep -Milliseconds 250
        $launched = @(
            Get-Process -Name ([System.IO.Path]::GetFileNameWithoutExtension($executablePath)) `
                -ErrorAction SilentlyContinue |
            Where-Object {
                $_.StartTime -ge $startedAt -and
                $_.Path -eq $executablePath
            }
        )
        $windowProcess = $launched |
            Where-Object { $_.MainWindowTitle -like "Trade Helper*" } |
            Select-Object -First 1
    }
    if (-not $windowProcess) {
        if ($parent.HasExited) {
            throw "TradeHelper exited before opening a window: $($parent.ExitCode)"
        }
        throw "TradeHelper did not open its main window within $TimeoutSeconds seconds"
    }
    if (-not $windowProcess.Responding) {
        throw "TradeHelper main window is not responding"
    }
    Write-Host "GUI smoke passed: $($windowProcess.MainWindowTitle)"
}
finally {
    foreach ($process in $launched | Sort-Object Id -Descending) {
        if ($process.HasExited) {
            continue
        }
        if ($process.MainWindowHandle -ne 0) {
            $null = $process.CloseMainWindow()
            $null = $process.WaitForExit(5000)
        }
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
    }
    if ($parent -and -not $parent.HasExited) {
        if (-not $parent.WaitForExit(5000)) {
            Stop-Process -Id $parent.Id -Force
        }
    }
    $env:TRADE_HELPER_DB = $previousDatabase
}
