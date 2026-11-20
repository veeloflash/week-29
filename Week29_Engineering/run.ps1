$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (Test-Path -LiteralPath $localPython) {
    & $localPython (Join-Path $PSScriptRoot 'app.py') @args
} else {
    & python (Join-Path $PSScriptRoot 'app.py') @args
}
exit $LASTEXITCODE
