param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"

& $Python -m unittest discover -s (Join-Path $projectRoot "tests") -v
exit $LASTEXITCODE
